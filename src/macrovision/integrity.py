from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError


class IntegrityConflictError(Exception):
    """A safe public conflict without raw database details."""


def commit_or_conflict(
    session: Session,
    message: str = "Update conflicted with existing or concurrent data",
) -> None:
    try:
        session.commit()
    except (IntegrityError, StaleDataError) as exc:
        session.rollback()
        raise IntegrityConflictError(message) from exc
