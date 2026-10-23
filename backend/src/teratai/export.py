"""predictions.csv export. Reads only the immutable agent_decision, never human_action or edited replies."""

import argparse
import csv
import sys
from pathlib import Path
from typing import TextIO

from teratai import db
from teratai.models import CSV_COLUMNS, AgentDecision


def rows(run_id: str) -> list[dict[str, str]]:
    with db.connect() as con:
        found = con.execute(
            "SELECT agent_decision FROM cases WHERE run_id=? AND status='done' ORDER BY complaint_id",
            (run_id,),
        ).fetchall()
    return [AgentDecision.model_validate_json(r["agent_decision"]).to_csv_row() for r in found]


def write_csv(run_id: str, fh: TextIO) -> int:
    data = rows(run_id)
    w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    w.writeheader()
    w.writerows(data)
    return len(data)


def summary(run_id: str) -> dict[str, int]:
    out = {"done": 0, "processing": 0, "error": 0}
    with db.connect() as con:
        for r in con.execute("SELECT status, COUNT(*) AS n FROM cases WHERE run_id=? GROUP BY status", (run_id,)):
            out[r["status"]] = out.get(r["status"], 0) + int(r["n"])
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Export predictions.csv from stored agent decisions")
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    with Path(a.out).open("w", encoding="utf-8", newline="") as fh:
        n = write_csv(a.run, fh)
    s = summary(a.run)
    print(f"wrote {n} rows to {a.out}")
    print(f"summary: {s}")
    return 1 if n == 0 or s["processing"] or s["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
