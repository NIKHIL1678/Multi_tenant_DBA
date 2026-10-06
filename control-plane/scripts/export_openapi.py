"""Write the API schema that the dashboard's TypeScript types are generated from.

    uv run python scripts/export_openapi.py      ->  ../dashboard/openapi.json

CI runs this and fails if the committed file is out of date, so the dashboard can never
silently drift from the real API.
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT.parent / "dashboard" / "openapi.json"

# The schema must not depend on local settings: no dev-only routes, any valid secret.
os.environ["DEV_AUTH"] = "false"
os.environ["APP_ENV"] = "test"
os.environ.setdefault("JWT_SECRET", "schema-export-only-" + "x" * 32)
sys.path.insert(0, str(ROOT))

from app.main import create_app  # noqa: E402 - must come after the environment is set


def main() -> None:
    schema = create_app().openapi()
    OUT.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT.parent)} ({len(schema['paths'])} paths)")


if __name__ == "__main__":
    main()
