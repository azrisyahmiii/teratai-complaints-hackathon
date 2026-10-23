"""Honest evaluation harness (robustness review §1, §4): messy-text scoring with uncertainty, and group-K-fold.

    python -m teratai.evaluate --set messy_dev                       # live mode, template replies
    python -m teratai.evaluate --set messy_dev --mode batch
    python -m teratai.evaluate --set path/to/rows.csv --labels path/to/labels.csv --out rows.csv
    python -m teratai.evaluate --set messy_holdout --i-am-scoring-the-holdout   # CP2 and freeze only
    python -m teratai.evaluate --groupkfold                          # classifier accuracy on unseen templates

Scoring reuses `scoring/score.py` (WEIGHTS, GATED, field_ok, money) so the numbers are the leaderboard's. The extra
columns of a rows file (e.g. `source_id`) are ignored. Nothing here changes the pipeline.
"""

import argparse
import csv
import json
import os
import random
import sys
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from teratai import config
from teratai.models import AgentDecision, ComplaintRow, Emit, StageEvent

sys.path.insert(0, str(config.BACKEND_DIR.parent / "scoring"))
import score as official

FIXTURES = config.BACKEND_DIR / "tests" / "core" / "fixtures"
SETS = {
    "messy_dev": (FIXTURES / "messy_dev.csv", FIXTURES / "messy_dev_labels.csv"),
    "messy_holdout": (FIXTURES / "holdout" / "messy_holdout.csv", FIXTURES / "holdout" / "messy_holdout_labels.csv"),
}
HOLDOUT_FLAG = "--i-am-scoring-the-holdout"
BOOTSTRAP_RESAMPLES = 1000
BOOTSTRAP_SEED = 20261023
FIELDS = tuple(official.WEIGHTS)  # matched_txn_id, outcome, refund_amount_myr, category, priority, reply_language
CLUSTER_THRESHOLD = 0.9
GROUP_FOLDS = 5

Process = Callable[[ComplaintRow, str, Emit | None], AgentDecision]


# --- loading -------------------------------------------------------------------------------------------------


def is_holdout(set_arg: str) -> bool:
    p = Path(set_arg)
    return set_arg == "messy_holdout" or "holdout" in {part.lower() for part in p.parts} or "holdout" in p.stem.lower()


def check_holdout_guard(set_arg: str, flag: bool) -> None:
    """The hold-out is scored at CP2 and at freeze only; refuse without the explicit flag."""
    if is_holdout(set_arg):
        if not flag:
            raise SystemExit(f"refusing to score the hold-out without {HOLDOUT_FLAG} (it must never be used for tuning)")
        print("WARNING: scoring the blind hold-out. Do not tune against this number.", file=sys.stderr)


def resolve_paths(set_arg: str, labels_arg: str | None) -> tuple[Path, Path]:
    if set_arg in SETS:
        rows_path, labels_path = SETS[set_arg]
    else:
        rows_path = Path(set_arg)
        labels_path = Path(labels_arg) if labels_arg else rows_path.with_name(rows_path.stem + "_labels.csv")
    if labels_arg:
        labels_path = Path(labels_arg)
    return rows_path, labels_path


def load_rows(path: Path) -> list[ComplaintRow]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return [
            ComplaintRow(
                complaint_id=r["complaint_id"],
                customer_id=r["customer_id"],
                received_at=r["received_at"],  # type: ignore[arg-type]  # pydantic parses the string
                channel=r["channel"],  # type: ignore[arg-type]
                subject=r.get("subject", "") or "",
                text=r["text"],
            )
            for r in csv.DictReader(fh)
        ]


def load_labels(path: Path) -> dict[str, dict[str, str]]:
    labels, _ = official.load(str(path))
    return labels


# --- scoring (the official rules) ----------------------------------------------------------------------------


@dataclass
class RowScore:
    complaint_id: str
    points: int
    hits: dict[str, bool]
    critical: str | None  # "wrongful refund" | "missed fraud" | None
    first_wrong: str | None  # first field (in weight order) that lost points


@dataclass
class Scored:
    rows: list[RowScore]

    @property
    def n(self) -> int:
        return len(self.rows)

    @property
    def mean(self) -> float:
        return sum(r.points for r in self.rows) / self.n if self.n else 0.0

    @property
    def criticals(self) -> int:
        return sum(1 for r in self.rows if r.critical)

    @property
    def final(self) -> float:
        return final_score([r.points for r in self.rows], self.criticals)

    def field_accuracy(self) -> dict[str, float]:
        return {f: sum(r.hits[f] for r in self.rows) / self.n for f in FIELDS} if self.n else {}


def final_score(points: list[int], criticals: int) -> float:
    n = len(points)
    return max(0.0, (sum(points) / n) * (1 - 2 * criticals / n)) if n else 0.0


def score_row(cid: str, pred: dict[str, str] | None, gold: dict[str, str]) -> RowScore:
    """One complaint, exactly as `scoring/score.py` does it. A missing prediction scores 0."""
    if pred is None:
        return RowScore(cid, 0, dict.fromkeys(FIELDS, False), None, FIELDS[0])
    hits = {f: official.field_ok(f, pred.get(f, ""), gold[f]) for f in FIELDS}
    for f in official.GATED:
        hits[f] = hits[f] and hits["matched_txn_id"]
    points = sum(official.WEIGHTS[f] for f, ok in hits.items() if ok)
    critical = None
    if (official.money(pred.get("refund_amount_myr", "")) or 0) > 0 and gold["outcome"] in ("DECLINE", "INVESTIGATE"):
        critical = "wrongful refund"
    if gold["outcome"] == "INVESTIGATE" and pred.get("outcome", "").upper() != "INVESTIGATE":
        critical = "missed fraud"
    first = next((f for f in FIELDS if not hits[f]), None)
    return RowScore(cid, points, hits, critical, first)


def score_all(preds: dict[str, dict[str, str]], labels: dict[str, dict[str, str]]) -> Scored:
    return Scored([score_row(cid, preds.get(cid), gold) for cid, gold in labels.items()])


def bootstrap_interval(
    points: list[int], criticals: list[bool], resamples: int = BOOTSTRAP_RESAMPLES, seed: int = BOOTSTRAP_SEED
) -> tuple[float, float]:
    """95% percentile interval of the FINAL score (mean x (1 - 2 x critical rate)) over row resamples."""
    n = len(points)
    if n == 0:
        return 0.0, 0.0
    rng = random.Random(seed)
    finals: list[float] = []
    for _ in range(resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        finals.append(final_score([points[i] for i in idx], sum(criticals[i] for i in idx)))
    finals.sort()
    return finals[int(0.025 * resamples)], finals[int(0.975 * resamples) - 1]


# --- running -------------------------------------------------------------------------------------------------


@dataclass
class RowRun:
    row: ComplaintRow
    decision: AgentDecision | None = None
    error: str | None = None
    match_status: str = ""
    match_reason: str = ""
    events: list[StageEvent] = field(default_factory=list)


def run_rows(rows: list[ComplaintRow], process: Process, run_id: str, concurrency: int) -> dict[str, RowRun]:
    def one(row: ComplaintRow) -> RowRun:
        rr = RowRun(row)
        try:
            rr.decision = process(row, run_id, rr.events.append)
        except Exception as e:  # noqa: BLE001  (one bad row must not stop the run; it scores 0 and is reported)
            rr.error = f"{type(e).__name__}: {e}"
        for ev in rr.events:
            if ev.stage == "match":
                rr.match_status = str(ev.payload.get("status") or "")
                rr.match_reason = str(ev.payload.get("reason") or "")
        return rr

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        results = list(pool.map(one, rows))
    return {r.row.complaint_id or "": r for r in results}


def predictions(runs: dict[str, RowRun]) -> dict[str, dict[str, str]]:
    return {cid: r.decision.to_csv_row() for cid, r in runs.items() if r.decision is not None}


def bucket(rs: RowScore, run: RowRun | None, gold: dict[str, str], pred: dict[str, str] | None) -> str:
    """Root-cause bucket for the first wrong field of a row that lost points."""
    if rs.first_wrong is None:
        return ""
    if run is not None and run.error:
        return f"error: {run.error.split(':')[0]}"
    f = rs.first_wrong
    if f == "matched_txn_id":
        got = (pred or {}).get("matched_txn_id", "")
        if got:
            return "txn: spurious txn" if not gold["matched_txn_id"] else "txn: wrong txn"
        status = run.match_status if run else "?"
        reason = run.match_reason if run else ""
        return f"txn: match {status}" + (f"/{reason}" if reason else "")
    return {"refund_amount_myr": "refund", "reply_language": "language"}.get(f, f)


def taxonomy(scored: Scored, runs: dict[str, RowRun], labels: dict[str, dict[str, str]]) -> Counter[str]:
    preds = predictions(runs)
    c: Counter[str] = Counter()
    for rs in scored.rows:
        if rs.points < sum(official.WEIGHTS.values()):
            c[bucket(rs, runs.get(rs.complaint_id), labels[rs.complaint_id], preds.get(rs.complaint_id)) or "other"] += 1
    return c


def report(scored: Scored, runs: dict[str, RowRun], labels: dict[str, dict[str, str]], title: str) -> str:
    lo, hi = bootstrap_interval([r.points for r in scored.rows], [bool(r.critical) for r in scored.rows])
    lines = [f"== {title}: n={scored.n} ==", f"{'field':<20}{'accuracy':>10}{'weight':>8}"]
    for f, acc in scored.field_accuracy().items():
        lines.append(f"{f:<20}{acc:>10.1%}{official.WEIGHTS[f]:>8}")
    kinds = Counter(r.critical for r in scored.rows if r.critical)
    lines.append(f"mean points    {scored.mean:.2f}")
    lines.append(f"criticals      {scored.criticals} ({', '.join(f'{k}: {v}' for k, v in kinds.items()) or 'none'})")
    lines.append(f"FINAL SCORE    {scored.final:.2f}   95% bootstrap interval [{lo:.2f}, {hi:.2f}] ({BOOTSTRAP_RESAMPLES} resamples)")
    errors = sum(1 for r in runs.values() if r.error)
    if errors:
        lines.append(f"pipeline errors {errors} (scored 0)")
    lines.append("miss taxonomy (rows losing points, by first wrong field):")
    for k, v in taxonomy(scored, runs, labels).most_common():
        lines.append(f"  {v:>3}  {k}")
    return "\n".join(lines)


def write_details(path: Path, scored: Scored, runs: dict[str, RowRun], labels: dict[str, dict[str, str]]) -> None:
    preds = predictions(runs)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            ["complaint_id", "points", "bucket", "critical"]
            + [f"{p}_{f}" for f in FIELDS for p in ("gold", "pred")]
            + ["match_status", "match_reason", "understanding_source", "clues", "flags", "text", "error"]
        )
        for rs in scored.rows:
            run = runs.get(rs.complaint_id)
            gold = labels[rs.complaint_id]
            pred = preds.get(rs.complaint_id)
            d = run.decision if run else None
            clues = json.dumps(d.understanding.issues[0].model_dump(mode="json"), ensure_ascii=False) if d else ""
            w.writerow(
                [rs.complaint_id, rs.points, bucket(rs, run, gold, pred), rs.critical or ""]
                + [v for f in FIELDS for v in (gold[f], (pred or {}).get(f, ""))]
                + [
                    run.match_status if run else "",
                    run.match_reason if run else "",
                    d.understanding.source if d else "",
                    clues,
                    ",".join(d.flags) if d else "",
                    run.row.text if run else "",
                    run.error or "" if run else "",
                ]
            )


def evaluate(
    rows: list[ComplaintRow], labels: dict[str, dict[str, str]], process: Process, run_id: str, concurrency: int
) -> tuple[Scored, dict[str, RowRun]]:
    runs = run_rows([r for r in rows if r.complaint_id in labels], process, run_id, concurrency)
    return score_all(predictions(runs), labels), runs


# --- group-K-fold: the honest classifier number --------------------------------------------------------------


def mask_text(text: str) -> str:
    """Remove what changes between instances of one template: amounts, digits, capitalised spans (names, merchants)."""
    import re

    t = re.sub(r"RM\s?[\d,]+(\.\d+)?", " ", text)
    t = re.sub(r"\d+", " ", t)
    t = re.sub(r"\b[A-Z][\w&'./-]*(?:\s+[A-Z][\w&'./-]*)*", " ", t)
    return t.lower()


def template_groups(texts: list[str], threshold: float) -> Any:
    """Connected components of the masked-text cosine graph (word 1-2 gram TF-IDF) at `threshold`."""
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components
    from sklearn.feature_extraction.text import TfidfVectorizer

    a = TfidfVectorizer(analyzer="word", ngram_range=(1, 2)).fit_transform([mask_text(t) for t in texts])
    sim = (a @ a.T).toarray()
    _, groups = connected_components(csr_matrix(sim >= threshold))
    return groups


def groupkfold_report(threshold: float = CLUSTER_THRESHOLD, folds: int = GROUP_FOLDS) -> str:
    import numpy as np
    from sklearn.model_selection import GroupKFold, cross_val_predict

    from teratai import classify

    _, texts, y = classify._training_set()
    y_arr = np.array(y)
    groups = template_groups(texts, threshold)
    probs = cross_val_predict(classify._build_pipeline(), texts, y_arr, cv=GroupKFold(n_splits=folds), groups=groups, method="predict_proba")
    classes = sorted(set(y))
    pred = np.array(classes)[probs.argmax(axis=1)]
    conf = probs.max(axis=1)
    correct = pred == y_arr
    tau = classify.tau()
    wrong = ~correct
    lines = [
        f"== group-K-fold ({folds} folds, cosine >= {threshold} on masked word 1-2 grams) ==",
        f"templates (clusters): {len(set(groups.tolist()))} over {len(texts)} complaints",
        f"accuracy (unseen templates): {correct.mean():.4f}   [stratified OOF in production is leaky: {classify._artifact().stats['oof_accuracy']:.4f}]",
        f"current tau {tau:.4f}: share below tau {float((conf < tau).mean()):.1%}; accuracy of accepted {float(correct[conf >= tau].mean()):.4f}",
        "top confusions (true -> predicted):",
    ]
    for (t, p), n in Counter(zip(y_arr[wrong].tolist(), pred[wrong].tolist(), strict=True)).most_common(6):
        lines.append(f"  {n:>3}  {t} -> {p}")
    best = None
    for t in np.unique(conf):
        acc = float(correct[conf >= t].mean())
        if acc >= 0.99:
            best = (float(t), acc, float((conf < t).mean()))
            break
    if best:
        lines.append(f"tau for >= 99% accepted accuracy under group-K-fold: {best[0]:.4f} (accepted accuracy {best[1]:.4f}, {best[2]:.1%} of items go to the LLM)")
    else:
        lines.append("no tau reaches 99% accepted accuracy under group-K-fold")
    return "\n".join(lines)


# --- CLI -----------------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None, process: Process | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", dest="set_name", help="messy_dev | messy_holdout | path to a complaints-format CSV")
    ap.add_argument("--labels", help="labels CSV (default: <set>_labels.csv)")
    ap.add_argument("--mode", choices=("live", "batch"), default="live")
    ap.add_argument("--replies", choices=("template", "llm"), default="template")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--out", help="per-row details CSV")
    ap.add_argument(HOLDOUT_FLAG, dest="holdout_ok", action="store_true")
    ap.add_argument("--groupkfold", action="store_true")
    ap.add_argument("--threshold", type=float, default=CLUSTER_THRESHOLD)
    args = ap.parse_args(argv)
    if not args.set_name and not args.groupkfold:
        ap.error("give --set and/or --groupkfold")
    if args.set_name:
        check_holdout_guard(args.set_name, args.holdout_ok)
        os.environ["REPLY_MODE"] = args.replies
        from teratai import pipeline

        rows_path, labels_path = resolve_paths(args.set_name, args.labels)
        labels = load_labels(labels_path)
        scored, runs = evaluate(
            load_rows(rows_path), labels, process or pipeline.process_complaint, "live" if args.mode == "live" else "eval", args.concurrency
        )
        print(report(scored, runs, labels, f"{args.set_name} / {args.mode} / replies={args.replies}"))
        if args.out:
            write_details(Path(args.out), scored, runs, labels)
            print(f"per-row details: {args.out}")
    if args.groupkfold:
        print(groupkfold_report(args.threshold))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
