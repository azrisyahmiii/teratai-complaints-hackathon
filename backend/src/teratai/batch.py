"""Batch CLI and scoring loop (SPEC §4.1, §12, §17). Same `process_complaint` as the live path, with `run_id` set.

    python -m teratai.batch --ids ../data/labels_train.csv --run dev --replies template --out predictions.csv

- `--ids`: a CSV with a `complaint_id` column (labels_train.csv, test_ids.csv) or a comma list of IDs.
- `--run`: the run id (never "live": eval runs are isolated, SPEC §2).
- `--replies template|llm`: sets the env var `REPLY_MODE` before the run; `reply.write_reply` reads it to choose the
  deterministic template path (`template`) or the LLM path (`llm`, default).
- Resume by ID: every finished decision is appended to `VAR_DIR/batch/<run>.jsonl` (`AgentDecision` as JSON).
  The first line is a stamp: reply mode + a fingerprint of the `teratai` source (and the classifier MODEL_VERSION).
  A rerun skips IDs already in the file, but refuses (exit 2) when the stamp differs from this run's: a resumed row
  keeps the decision it was made with, so mixing modes or code versions would be silent. `--fresh` deletes the file.
- Errors: one row that raises is logged and counted, the run continues. Its output row carries the SPEC §6
  NEEDS_INFO defaults by category (SCAM / UNAUTHORISED: INVESTIGATE + FRAUD_TEAM; else DECLINE + HUMAN_APPROVAL; no
  refund, no transaction; INVESTIGATE + FRAUD_TEAM if the category cannot be told), so the CSV always has every ID,
  and a later rerun retries it (errors are never checkpointed). Never a refund, so never a critical error.
- `--persist`: calls `pipeline.store(row, decision)` for every row (idempotent by complaint_id once Platform lands).
- `--dist`: prints category/outcome/route/priority/reply_language shares vs labels_train.csv, flags > 5 pp shifts.
- Only `AgentDecision.to_csv_row()` feeds the CSV. Written with the `csv` module, UTF-8.
"""

import argparse
import contextlib
import csv
import hashlib
import json
import os
import sys
import threading
import time
import traceback
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from decimal import Decimal
from functools import cache
from pathlib import Path

from teratai import classify, config, data, lang, pipeline, policy
from teratai.models import (
    CSV_COLUMNS,
    AgentDecision,
    Category,
    ComplaintRow,
    Emit,
    Outcome,
    Priority,
    StageEvent,
)

DIST_FIELDS = ("category", "outcome", "route", "priority", "reply_language")

Process = Callable[[ComplaintRow, str, Emit | None], AgentDecision]
Store = Callable[[ComplaintRow, AgentDecision], int]
Lookup = Callable[[str], ComplaintRow]

# categories whose NEEDS_INFO default is INVESTIGATE (SPEC §6), the same set as policy's
FRAUD_CATEGORIES: frozenset[str] = frozenset({"SCAM_TRANSFER", "UNAUTHORISED_CARD"})

ERROR_REPLY = {
    "EN": "Thank you for contacting Teratai Bank. We need more details to review your complaint and will be in touch.",
    "MS": "Terima kasih kerana menghubungi Teratai Bank. Kami memerlukan maklumat lanjut untuk menyemak aduan anda.",
}


# --- results --------------------------------------------------------------------------------------------


@dataclass
class BatchResult:
    run_id: str
    rows: list[dict[str, str]] = field(default_factory=list)  # CSV rows in input order
    decisions: dict[str, AgentDecision] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)  # complaint_id -> "ExcType: message"
    resumed: int = 0
    wall_s: float = 0.0
    latencies_ms: list[float] = field(default_factory=list)  # per case processed in this session
    cost_usd: float = 0.0
    llm_cases: int = 0  # cases in this session with at least one stage event that names a model
    processed: int = 0  # cases processed in this session (excludes resumed)


@dataclass(frozen=True)
class Shift:
    field: str
    value: str
    run_pct: float
    train_pct: float

    @property
    def diff_pp(self) -> float:
        return self.run_pct - self.train_pct


# --- ids, checkpoint, csv ---------------------------------------------------------------------------------


def read_ids(spec: str) -> list[str]:
    """A CSV path with a `complaint_id` column, or a comma list of IDs. Order kept, duplicates dropped."""
    p = Path(spec)
    if p.is_file():
        with p.open(newline="", encoding="utf-8-sig") as fh:
            ids = [r["complaint_id"].strip() for r in csv.DictReader(fh)]
    else:
        ids = [s.strip() for s in spec.split(",")]
    return list(dict.fromkeys(i for i in ids if i))


class CheckpointMismatch(RuntimeError):
    """The run's checkpoint was made with a different reply mode or code version."""


@cache
def code_fingerprint() -> str:
    """12 hex chars over every `teratai` source file plus the classifier MODEL_VERSION."""
    h = hashlib.sha1(f"classify.MODEL_VERSION={classify.MODEL_VERSION}".encode())
    pkg = Path(__file__).resolve().parent
    for p in sorted(pkg.rglob("*.py")):
        h.update(p.relative_to(pkg).as_posix().encode())
        h.update(p.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:12]


def checkpoint_path(run_id: str, directory: Path | None = None) -> Path:
    return (directory or config.VAR_DIR / "batch") / f"{run_id}.jsonl"


def stamp_line(replies: str, code: str) -> str:
    return json.dumps({"_stamp": {"replies": replies, "code": code}}) + "\n"


def read_stamp(path: Path) -> tuple[str, str] | None:
    """(reply mode, code fingerprint) from the checkpoint's first line, None if it has no stamp."""
    with path.open(encoding="utf-8") as fh:
        first = fh.readline()
    try:
        stamp = json.loads(first)["_stamp"]
        return str(stamp["replies"]), str(stamp["code"])
    except (ValueError, KeyError, TypeError):
        return None


def check_stamp(path: Path, replies: str, code: str) -> None:
    """Raise CheckpointMismatch unless the existing checkpoint was made with this reply mode and code."""
    if not path.is_file() or path.stat().st_size == 0:
        return
    found = read_stamp(path)
    if found == (replies, code):
        return
    was = f"replies={found[0]}, code={found[1]}" if found else "no stamp (made by an older version)"
    raise CheckpointMismatch(
        f"checkpoint {path.name} was made with {was}; this run is replies={replies}, code={code}. "
        "Rerun with --fresh to start over."
    )


def load_checkpoint(path: Path) -> dict[str, AgentDecision]:
    """Decisions finished by an earlier run. The stamp line and a torn last line (killed mid-write) are ignored."""
    done: dict[str, AgentDecision] = {}
    if not path.is_file():
        return done
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                d = AgentDecision.model_validate_json(line)
            except ValueError:
                continue
            done[d.complaint_id] = d
    return done


def write_csv(path: Path, rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="raise")
        w.writeheader()
        w.writerows(rows)


def _noop(_event: StageEvent) -> None:
    return None


def error_row(complaint_id: str, lookup: Lookup = data.complaint) -> dict[str, str]:
    """SPEC §6 NEEDS_INFO defaults for a row the pipeline could not process. Never a refund.

    Each piece is recovered in its own try: language from the row, category from `classify.understand`, priority from
    the policy's base priority (+65 bump). Whatever cannot be recovered keeps the safe default (INVESTIGATE, FRAUD_TEAM).
    """
    row: ComplaintRow | None = None
    with contextlib.suppress(Exception):  # unknown id: the defaults below are enough
        row = lookup(complaint_id)
    language = "EN"
    category: Category | None = None
    priority: Priority = "P2"
    if row is not None:
        with contextlib.suppress(Exception):
            language = lang.reply_language(row)[0]
        with contextlib.suppress(Exception):
            category = classify.understand(row, "batch", _noop).issues[0].category
        if category is not None:
            with contextlib.suppress(Exception):
                priority = policy.priority_for(category, row)[0]
    outcome: Outcome = (
        "DECLINE" if category is not None and category not in FRAUD_CATEGORIES else "INVESTIGATE"
    )
    return {
        "complaint_id": complaint_id,
        "category": category or "SERVICE_QUALITY",
        "matched_txn_id": "",
        "outcome": outcome,
        "refund_amount_myr": "0.00",
        "priority": priority,
        "reply_language": language,
        "route": policy.route_for(outcome, Decimal("0.00")),
        "reply_text": ERROR_REPLY.get(language, ERROR_REPLY["EN"]),
    }


# --- distribution check -----------------------------------------------------------------------------------


def _shares(values: Sequence[str]) -> dict[str, float]:
    n = len(values)
    return {k: 100.0 * v / n for k, v in Counter(values).items()} if n else {}


def dist_shifts(
    rows: Sequence[dict[str, str]],
    train_rows: Sequence[dict[str, str]],
    tolerance_pp: float = config.DIST_TOLERANCE_PP,
) -> list[Shift]:
    """Every (field, value) whose share in `rows` differs from `train_rows` by more than `tolerance_pp`."""
    out: list[Shift] = []
    for f in DIST_FIELDS:
        run, train = _shares([r[f] for r in rows]), _shares([r[f] for r in train_rows])
        for v in sorted(set(run) | set(train)):
            s = Shift(f, v, run.get(v, 0.0), train.get(v, 0.0))
            if abs(s.diff_pp) > tolerance_pp:
                out.append(s)
    return out


def train_label_rows() -> list[dict[str, str]]:
    return [{f: getattr(lb, f) for f in DIST_FIELDS} for lb in data.labels().values()]


def format_dist(rows: Sequence[dict[str, str]], train_rows: Sequence[dict[str, str]]) -> str:
    lines = [f"Distribution vs labels_train.csv ({len(rows)} rows vs {len(train_rows)}), shares in %"]
    for f in DIST_FIELDS:
        run, train = _shares([r[f] for r in rows]), _shares([r[f] for r in train_rows])
        parts = [f"{v} {run.get(v, 0.0):.1f}/{train.get(v, 0.0):.1f}" for v in sorted(set(run) | set(train))]
        lines.append(f"  {f:<15} " + "  ".join(parts))
    shifts = dist_shifts(rows, train_rows)
    if shifts:
        lines.append(
            f"  FLAG: {len(shifts)} share(s) differ by more than {config.DIST_TOLERANCE_PP:.0f} pp (run/train):"
        )
        lines += [
            f"    {s.field}={s.value}: {s.run_pct:.1f} vs {s.train_pct:.1f} ({s.diff_pp:+.1f} pp)"
            for s in shifts
        ]
    else:
        lines.append(f"  OK: every share within {config.DIST_TOLERANCE_PP:.0f} pp of training")
    return "\n".join(lines)


# --- the run ----------------------------------------------------------------------------------------------


@dataclass
class _Outcome:
    decision: AgentDecision | None
    error: str | None
    latency_ms: float
    cost_usd: float
    used_llm: bool


def _run_one(row: ComplaintRow, run_id: str, process: Process) -> _Outcome:
    events: list[StageEvent] = []
    t0 = time.perf_counter()
    try:
        decision = process(row, run_id, events.append)
    except Exception as exc:  # noqa: BLE001  # one bad row must not kill the run
        trace = traceback.format_exc(limit=3)
        print(f"ERROR {row.complaint_id}: {type(exc).__name__}: {exc}\n{trace}", file=sys.stderr)
        return _Outcome(None, f"{type(exc).__name__}: {exc}", (time.perf_counter() - t0) * 1000, 0.0, False)
    cost = sum(float(e.cost_usd) for e in events)
    return _Outcome(decision, None, (time.perf_counter() - t0) * 1000, cost, any(e.model for e in events))


def run_batch(
    ids: Sequence[str],
    run_id: str,
    *,
    concurrency: int = config.BATCH_CONCURRENCY,
    fresh: bool = False,
    persist: bool = False,
    replies: str | None = None,
    process: Process = pipeline.process_complaint,
    store: Store = pipeline.store,
    lookup: Lookup = data.complaint,
    checkpoint_dir: Path | None = None,
) -> BatchResult:
    if run_id == "live":
        raise ValueError("run_id 'live' is reserved for the live path; pick another run id")
    t_start = time.perf_counter()
    ck = checkpoint_path(run_id, checkpoint_dir)
    ck.parent.mkdir(parents=True, exist_ok=True)
    mode = replies or os.environ.get("REPLY_MODE", "llm")
    code = code_fingerprint()
    if fresh and ck.exists():
        ck.unlink()
    check_stamp(ck, mode, code)
    if not ck.exists() or ck.stat().st_size == 0:
        ck.write_text(stamp_line(mode, code), encoding="utf-8")
    done = load_checkpoint(ck)
    res = BatchResult(run_id=run_id)
    res.decisions = {i: done[i] for i in ids if i in done}
    res.resumed = len(res.decisions)

    todo: list[tuple[str, ComplaintRow]] = []
    for cid in ids:
        if cid in res.decisions:
            continue
        try:
            todo.append((cid, lookup(cid)))
        except Exception as exc:  # noqa: BLE001  # report and continue
            res.errors[cid] = f"{type(exc).__name__}: {exc}"
            print(f"ERROR {cid}: unknown complaint ({exc})", file=sys.stderr)

    lock = threading.Lock()
    with ck.open("a", encoding="utf-8") as fh, ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        # run the first row alone so the classifier artifact, data caches and LLM clients warm up once
        warm = todo[:1]
        for batch in (warm, todo[1:]):
            futures = {pool.submit(_run_one, row, run_id, process): cid for cid, row in batch}
            for fut in as_completed(futures):
                cid = futures[fut]
                out = fut.result()
                res.processed += 1
                res.latencies_ms.append(out.latency_ms)
                res.cost_usd += out.cost_usd
                res.llm_cases += out.used_llm
                if out.decision is None:
                    res.errors[cid] = out.error or "unknown error"
                    continue
                res.decisions[cid] = out.decision
                with lock:  # checkpoint as we go, so a killed run resumes
                    fh.write(json.dumps(out.decision.model_dump(mode="json"), ensure_ascii=False) + "\n")
                    fh.flush()

    rows_by_id = {cid: row for cid, row in todo}
    for cid in ids:
        if cid in res.decisions:
            res.rows.append(res.decisions[cid].to_csv_row())
        else:
            res.rows.append(error_row(cid, lookup))
    if persist:
        for cid in ids:
            d = res.decisions.get(cid)
            if d is None:
                continue
            try:
                store(rows_by_id.get(cid) or lookup(cid), d)
            except Exception as exc:  # noqa: BLE001  # report and continue
                res.errors[cid] = f"store: {type(exc).__name__}: {exc}"
                print(f"ERROR {cid}: store failed ({exc})", file=sys.stderr)
    res.wall_s = time.perf_counter() - t_start
    return res


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, round(q * (len(s) - 1)))]


def summary(res: BatchResult) -> str:
    n = len(res.rows)
    share = 100.0 * res.llm_cases / res.processed if res.processed else 0.0
    lines = [
        (
            f"run {res.run_id}: {n} rows ({res.resumed} resumed, {res.processed} processed), "
            f"{len(res.errors)} errors, wall {res.wall_s:.1f}s"
        ),
        (
            f"latency per case (this session): p50 {_pct(res.latencies_ms, 0.5):.0f} ms, "
            f"p95 {_pct(res.latencies_ms, 0.95):.0f} ms"
        ),
        (
            f"LLM cost ${res.cost_usd:.4f} (${res.cost_usd / res.processed:.5f}/case), "
            f"LLM-call share {share:.1f}% of processed cases"
            if res.processed
            else f"LLM cost ${res.cost_usd:.4f}"
        ),
    ]
    if res.errors:
        lines.append("errors (written with safe INVESTIGATE defaults, retried on rerun):")
        lines += [f"  {cid}: {msg}" for cid, msg in list(res.errors.items())[:20]]
        if len(res.errors) > 20:
            lines.append(f"  ... and {len(res.errors) - 20} more")
    return "\n".join(lines)


# --- CLI --------------------------------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m teratai.batch", description=__doc__.split("\n\n")[0])
    ap.add_argument("--ids", required=True, help="CSV with a complaint_id column, or a comma list of IDs")
    ap.add_argument("--run", required=True, help="run id (not 'live')")
    ap.add_argument("--out", type=Path, help="predictions CSV to write")
    ap.add_argument("--concurrency", type=int, default=config.BATCH_CONCURRENCY)
    ap.add_argument("--replies", choices=("template", "llm"), default="llm", help="sets env REPLY_MODE")
    ap.add_argument("--persist", action="store_true", help="call pipeline.store for every row")
    ap.add_argument("--fresh", action="store_true", help="ignore and delete the run's checkpoint")
    ap.add_argument("--dist", action="store_true", help="compare output distributions with labels_train.csv")
    args = ap.parse_args(argv)

    os.environ["REPLY_MODE"] = args.replies
    ids = read_ids(args.ids)
    if not ids:
        print("no complaint ids", file=sys.stderr)
        return 2
    try:
        res = run_batch(
            ids,
            args.run,
            concurrency=args.concurrency,
            fresh=args.fresh,
            persist=args.persist,
            replies=args.replies,
        )
    except CheckpointMismatch as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.out:
        write_csv(args.out, res.rows)
        print(f"wrote {len(res.rows)} rows to {args.out}")
    print(summary(res))
    if args.dist:
        print(format_dist(res.rows, train_label_rows()))
    return 1 if res.errors else 0


if __name__ == "__main__":
    sys.exit(main())
