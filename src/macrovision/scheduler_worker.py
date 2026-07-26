import argparse
import logging
import os
import signal
import socket
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from threading import Event, Thread

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from macrovision.config import Settings, get_settings
from macrovision.database import SessionLocal
from macrovision.provider_registry import ProviderRegistry, get_provider_registry
from macrovision.scheduler_models import ProviderSyncRun
from macrovision.scheduler_schemas import ProviderSyncRunStatus
from macrovision.scheduler_services import (
    SessionFactory,
    claim_pending_runs,
    execute_claimed_run,
    materialize_due_schedules,
    recover_expired_runs,
    renew_lease,
)

ALEMBIC_HEAD = "20260724_0008"
logger = logging.getLogger("macrovision.scheduler")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def default_worker_id() -> str:
    value = f"{socket.gethostname()}-{os.getpid()}"
    return value[:128]


def verify_database(session_factory: SessionFactory) -> None:
    with session_factory() as session:
        version = session.scalar(text("SELECT version_num FROM alembic_version"))
    if version != ALEMBIC_HEAD:
        raise RuntimeError("Database schema is not at the required scheduler revision")


class LeaseHeartbeat:
    """Renew one run lease through independent short-lived sessions."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        run_id: int,
        worker_id: str,
        lease_generation: int,
        lease_seconds: int,
        heartbeat_seconds: int,
        now_factory: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._run_id = run_id
        self._worker_id = worker_id
        self._lease_generation = lease_generation
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._now_factory = now_factory
        self._stop = Event()
        self._thread: Thread | None = None
        self.lease_lost = False

    def _run(self) -> None:
        while not self._stop.wait(self._heartbeat_seconds):
            try:
                with self._session_factory() as session:
                    renewed = renew_lease(
                        session,
                        self._run_id,
                        worker_id=self._worker_id,
                        lease_generation=self._lease_generation,
                        now=self._now_factory(),
                        lease_seconds=self._lease_seconds,
                    )
                if not renewed:
                    self.lease_lost = True
                    return
            except SQLAlchemyError:
                self.lease_lost = True
                return

    def __enter__(self) -> "LeaseHeartbeat":
        self._thread = Thread(
            target=self._run,
            name=f"scheduler-heartbeat-{self._run_id}",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(self._heartbeat_seconds * 2, 1))


def execute_with_heartbeat(
    session_factory: SessionFactory,
    run: ProviderSyncRun,
    *,
    worker_id: str,
    registry: ProviderRegistry,
    settings: Settings,
    now_factory: Callable[[], datetime] = _utc_now,
    heartbeat_factory: type[LeaseHeartbeat] = LeaseHeartbeat,
) -> bool:
    with heartbeat_factory(
        session_factory,
        run_id=run.id,
        worker_id=worker_id,
        lease_generation=run.lease_generation,
        lease_seconds=settings.scheduler_lease_seconds,
        heartbeat_seconds=settings.scheduler_heartbeat_seconds,
        now_factory=now_factory,
    ):
        completed = execute_claimed_run(
            session_factory,
            run.id,
            worker_id=worker_id,
            lease_generation=run.lease_generation,
            registry=registry,
            settings=settings,
        )
    return completed


def run_cycle(
    *,
    session_factory: SessionFactory = SessionLocal,
    registry: ProviderRegistry | None = None,
    settings: Settings | None = None,
    worker_id: str | None = None,
    claim_limit: int | None = None,
    now_factory: Callable[[], datetime] = _utc_now,
    execute: Callable[..., bool] = execute_with_heartbeat,
) -> int:
    runtime_settings = settings or get_settings()
    runtime_registry = registry or get_provider_registry()
    identity = worker_id or default_worker_id()
    limit = claim_limit or runtime_settings.scheduler_claim_limit
    current = now_factory()
    with session_factory() as session:
        recover_expired_runs(
            session,
            now=current,
            limit=limit,
            base_seconds=runtime_settings.scheduler_retry_base_seconds,
            maximum_seconds=runtime_settings.scheduler_retry_max_seconds,
        )
    with session_factory() as session:
        materialize_due_schedules(
            session,
            now=current,
            limit=limit,
            maximum_attempts=runtime_settings.scheduler_maximum_attempts,
        )
    with session_factory() as session:
        claimed = claim_pending_runs(
            session,
            worker_id=identity,
            now=current,
            lease_seconds=runtime_settings.scheduler_lease_seconds,
            limit=limit,
        )
    for run in claimed:
        execute(
            session_factory,
            run,
            worker_id=identity,
            registry=runtime_registry,
            settings=runtime_settings,
            now_factory=now_factory,
        )
    failed = 0
    if claimed:
        with session_factory() as session:
            for run in claimed:
                persisted = session.get(ProviderSyncRun, run.id)
                if persisted is not None and persisted.status == ProviderSyncRunStatus.failed.value:
                    failed += 1
    return 1 if failed else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MacroVision scheduled provider worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=int)
    parser.add_argument("--claim-limit", type=int)
    parser.add_argument("--worker-id")
    return parser


def _validate_options(args: argparse.Namespace, settings: Settings) -> tuple[int, int, str]:
    poll_seconds = (
        settings.scheduler_poll_seconds if args.poll_seconds is None else args.poll_seconds
    )
    claim_limit = settings.scheduler_claim_limit if args.claim_limit is None else args.claim_limit
    worker_id = args.worker_id or default_worker_id()
    if not 1 <= poll_seconds <= 60:
        raise ValueError("poll-seconds must be between 1 and 60")
    if not 1 <= claim_limit <= 10:
        raise ValueError("claim-limit must be between 1 and 10")
    if not worker_id or len(worker_id) > 128:
        raise ValueError("worker-id must contain between 1 and 128 characters")
    return poll_seconds, claim_limit, worker_id


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        settings = get_settings()
        poll_seconds, claim_limit, worker_id = _validate_options(args, settings)
    except (SystemExit, ValidationError, ValueError):
        return 2
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        verify_database(SessionLocal)
    except (DBAPIError, RuntimeError):
        logger.error("Scheduler database preflight failed")
        return 3
    stop = Event()

    def request_shutdown(_signum: int, _frame: object) -> None:
        stop.set()

    if not args.once:
        signal.signal(signal.SIGINT, request_shutdown)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, request_shutdown)
    try:
        while True:
            result = run_cycle(
                settings=settings,
                worker_id=worker_id,
                claim_limit=claim_limit,
            )
            if args.once:
                return result
            if stop.wait(poll_seconds):
                return result
    except DBAPIError:
        logger.error("Scheduler database operation failed")
        return 3
    except Exception:
        logger.error("Scheduler cycle failed safely")
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
