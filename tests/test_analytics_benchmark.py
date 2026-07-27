import json
import sys
from typing import cast

import pytest

from macrovision import analytics_benchmark
from macrovision.analytics_benchmark import run_benchmark


def test_sqlite_benchmark_is_deterministic_and_replays() -> None:
    summary = run_benchmark(sizes=(10,))
    assert summary["backend"] == "sqlite"
    cases = cast(list[dict[str, object]], summary["cases"])
    assert len(cases) == 2
    assert {item["transformation"] for item in cases} == {
        "difference",
        "moving_average",
    }
    assert all(item["outputs"] == 10 for item in cases)
    assert all(item["replayed_run_id_matches"] is True for item in cases)
    assert all(
        float(cast(float, item["replay_seconds"])) < float(cast(float, item["total_seconds"]))
        for item in cases
    )


def test_postgresql_benchmark_requires_explicit_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MACROVISION_POSTGRES_BENCHMARK_URL", raising=False)
    with pytest.raises(RuntimeError, match="MACROVISION_POSTGRES_BENCHMARK_URL"):
        run_benchmark(sizes=(10,), postgres=True)


@pytest.mark.parametrize("as_json", [True, False])
def test_benchmark_command_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    as_json: bool,
) -> None:
    arguments = ["analytics-benchmark", "--sizes", "2"]
    if as_json:
        arguments.append("--json")
    monkeypatch.setattr(sys, "argv", arguments)
    analytics_benchmark.main()
    result = json.loads(capsys.readouterr().out)
    assert result["backend"] == "sqlite"
    assert len(result["cases"]) == 2
