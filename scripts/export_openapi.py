"""Export MacroVision's public OpenAPI contract without starting a server."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from macrovision.main import app

PRIVATE_FINGERPRINT_FIELDS = {
    "request_fingerprint",
    "snapshot_fingerprint",
    "reusable_fingerprint",
    "parameters_fingerprint",
}


def build_openapi_document() -> dict[str, Any]:
    """Build and validate the deterministic public OpenAPI document."""
    document = app.openapi()
    serialized = json.dumps(document, ensure_ascii=False, sort_keys=True)
    leaked = sorted(field for field in PRIVATE_FINGERPRINT_FIELDS if field in serialized)
    if leaked:
        raise RuntimeError(f"Private Analytics fields leaked into OpenAPI: {leaked}")
    return document


def export_openapi(output: Path) -> None:
    """Write stable UTF-8 JSON to an explicit file path."""
    if output.exists() and output.is_dir():
        raise ValueError(f"Output path is a directory: {output}")
    if not output.parent.exists():
        raise ValueError(f"Output directory does not exist: {output.parent}")

    document = build_openapi_document()
    payload = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    output.write_text(payload, encoding="utf-8", newline="\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        export_openapi(args.output)
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"OpenAPI export failed: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
