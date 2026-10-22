"""Write the OpenAPI schema to a file: `uv run python -m teratai.api.dump_openapi ../web/lib/api/openapi.json`."""

import json
import sys
from pathlib import Path

from teratai.api.main import app


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
