"""Write the API's OpenAPI document to frontend/openapi.json, from which the frontend generates its
TypeScript types (`npm run types` in frontend/). Built from `create_app` with the test fakes, so no
database, cache or model is needed.

    PYTHONPATH=src .venv/bin/python scripts/export_openapi.py [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]


def export(out: Path) -> dict:
    from fakes_api import build_app
    app, _ = build_app()
    spec = app.openapi()
    spec["info"]["description"] = ("PharmAssist v2 API. Every non-2xx response is ErrorOut. Authentication: "
                                   "Bearer access token from /auth/login; the refresh token is an HttpOnly cookie.")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
    return spec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Export the OpenAPI document for the frontend's type generation.")
    ap.add_argument("--out", type=Path, default=ROOT / "frontend" / "openapi.json")
    args = ap.parse_args(argv)
    spec = export(args.out)
    print(f"wrote {args.out} ({len(spec['paths'])} paths, {len(spec['components']['schemas'])} schemas)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
