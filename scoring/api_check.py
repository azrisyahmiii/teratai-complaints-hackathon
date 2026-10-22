"""Test your agent's API against the contract in docs/api.md, and score its answers.

Usage:
    python scoring/api_check.py http://localhost:8000              # 10 training complaints, plus the robustness probes
    python scoring/api_check.py http://localhost:8000 --n 30       # more complaints
    python scoring/api_check.py http://192.168.1.23:8000 --no-probes

The organisers run this same script in the live round with hidden complaints:
    python scoring/api_check.py <url> --complaints hidden_complaints.csv --labels hidden_labels.csv --all --out team.json

It sends every complaint at once (as concurrent POSTs), polls GET /cases/{id} until each is done, checks every field
against the contract, and scores the answers exactly like score.py (outcome and refund only count with the right
transaction; critical errors cost double). Standard library only.
"""
import argparse
import concurrent.futures as cf
import csv
import json
import random
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from score import GATED, WEIGHTS, field_ok, money

ROOT = Path(__file__).resolve().parent.parent
FIELDS = ["complaint_id", "customer_id", "received_at", "channel", "subject", "text"]
ALLOWED = {"category": {"DUPLICATE_CHARGE", "FAILED_TRANSFER", "ATM_NOT_DISPENSED", "UNAUTHORISED_CARD", "SCAM_TRANSFER", "FEE_DISPUTE", "SERVICE_QUALITY"},
           "outcome": {"REFUND", "DECLINE", "INVESTIGATE", "INFO_ONLY"}, "priority": {"P1", "P2", "P3"}, "reply_language": {"EN", "MS"},
           "route": {"AUTO_RESOLVE", "HUMAN_APPROVAL", "FRAUD_TEAM"}, "self_check": {"passed", "flagged"},
           "case_state": {"auto_resolved", "awaiting_approval", "with_fraud_team", "approved", "rejected"}}
STATE_FOR_ROUTE = {"AUTO_RESOLVE": ("auto_resolved", True), "HUMAN_APPROVAL": ("awaiting_approval", False), "FRAUD_TEAM": ("with_fraud_team", None)}
DECISION = ("category", "matched_txn_id", "outcome", "refund_amount_myr", "priority", "reply_language", "route", "reply_text")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def http(method, url, body=None, timeout=130):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:  # connection refused, timeout, bad JSON
        return None, str(e)


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def contract_problems(case):
    probs = []
    for f, allowed in ALLOWED.items():
        if case.get(f) not in allowed:
            probs.append(f"{f}={case.get(f)!r}")
    if money(str(case.get("refund_amount_myr", ""))) is None:
        probs.append(f"refund_amount_myr={case.get('refund_amount_myr')!r}")
    if not str(case.get("reply_text") or "").strip():
        probs.append("reply_text empty")
    if "matched_txn_id" not in case:
        probs.append("matched_txn_id missing")
    if not isinstance(case.get("sent"), bool):
        probs.append(f"sent={case.get('sent')!r} (must be true or false)")
    if "human_action" not in case:
        probs.append("human_action missing (null until a human acts)")
    return probs


def state_matches_route(case):
    """case_state and sent as the contract requires for the route the agent chose (before any human action)."""
    want = STATE_FOR_ROUTE.get(case.get("route"))
    if not want:
        return False
    state, sent = want
    return case.get("case_state") == state and (sent is None or case.get("sent") is sent)


def hitl_probes(base, results):
    """Human in the loop, on one case the team's agent routed to HUMAN_APPROVAL."""
    target = next((r["case"] for r in results if "case" in r and r["case"].get("route") == "HUMAN_APPROVAL"
                   and r["case"].get("case_state") == "awaiting_approval"), None)
    if target is None:
        return [("Human-in-the-loop probes (skipped: no case waiting for approval in this run)", False, None)]
    cid, url = target["complaint_id"], f"{base}/cases/{target['complaint_id']}"
    rows = [("Approval case waits: awaiting_approval and sent false", target.get("sent") is False, 200)]
    bad = {"action": "edit_approve", "actor": "api_check probe", "reason": "probe: invented amount",
           "reply_text": str(target.get("reply_text", "")) + " We have also credited RM987.65 to your account."}
    s, _ = http("POST", f"{url}/actions", bad, timeout=60)
    _, after = http("GET", url, timeout=30)
    held = isinstance(after, dict) and after.get("case_state") == "awaiting_approval" and after.get("sent") is False
    rows.append(("Edited reply with an invented amount is refused (4xx) and nothing is sent", s is not None and 400 <= s < 500 and held, s))
    s, _ = http("POST", f"{url}/actions", {"action": "approve", "actor": "api_check probe", "reason": "probe: approve"}, timeout=60)
    _, done = http("GET", url, timeout=30)
    ok = (s == 200 and isinstance(done, dict) and done.get("case_state") == "approved" and done.get("sent") is True
          and isinstance(done.get("human_action"), dict) and done["human_action"].get("actor") == "api_check probe"
          and all(done.get(k) == target.get(k) for k in DECISION))
    rows.append((f"Approve moves {cid} to approved, sent true, records the actor, keeps the agent's decision", ok, s))
    s, _ = http("POST", f"{url}/actions", {"action": "approve", "actor": "api_check probe", "reason": "again"}, timeout=60)
    rows.append(("Acting on a case that is no longer waiting returns 409", s == 409, s))
    return rows


def run_one(base, complaint, timeout):
    t0 = time.time()
    status, body = http("POST", f"{base}/complaints", {k: complaint.get(k, "") for k in FIELDS}, timeout=timeout)
    if status is None or status >= 300:
        return {"id": complaint["complaint_id"], "error": f"POST returned {status} {body if status is None else ''}".strip(), "seconds": time.time() - t0}
    while time.time() - t0 < timeout:
        status, case = http("GET", f"{base}/cases/{complaint['complaint_id']}", timeout=30)
        if status == 200 and isinstance(case, dict) and case.get("status") in ("done", "error"):
            return {"id": complaint["complaint_id"], "case": case, "seconds": time.time() - t0}
        time.sleep(2)
    return {"id": complaint["complaint_id"], "error": f"not done within {timeout}s", "seconds": time.time() - t0}


def probes(base, sample):
    rows = []
    s, _ = http("GET", f"{base}/health", timeout=10)
    rows.append(("GET /health returns 200", s == 200, s))
    s, _ = http("GET", f"{base}/cases/NO-SUCH-CASE-123", timeout=10)
    rows.append(("Unknown case ID returns 404", s == 404, s))
    bad = {k: sample[k] for k in FIELDS if k != "text"}
    s, _ = http("POST", f"{base}/complaints", bad, timeout=30)
    rows.append(("Complaint without text is rejected with 4xx", s is not None and 400 <= s < 500, s))
    s, _ = http("POST", f"{base}/complaints", {**{k: sample[k] for k in FIELDS}, "complaint_id": "PROBE-UNKNOWN-CUST", "customer_id": "CUS-99999"}, timeout=60)
    rows.append(("Unknown customer is handled without a 5xx", s is not None and s < 500, s))
    s1, before = http("GET", f"{base}/cases/{sample['complaint_id']}", timeout=30)
    s, _ = http("POST", f"{base}/complaints", {k: sample[k] for k in FIELDS}, timeout=60)
    time.sleep(2)
    s2, after = http("GET", f"{base}/cases/{sample['complaint_id']}", timeout=30)
    same = s2 == 200 and isinstance(before, dict) and isinstance(after, dict) and all(before.get(k) == after.get(k) for k in ("outcome", "matched_txn_id", "refund_amount_myr"))
    rows.append(("Posting the same complaint again doesn't change or duplicate the case", (s is not None and s < 500) and same, s))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base_url")
    ap.add_argument("--complaints", default=str(ROOT / "data" / "complaints.csv"))
    ap.add_argument("--labels", default=str(ROOT / "data" / "labels_train.csv"))
    ap.add_argument("--n", type=int, default=10, help="how many labelled complaints to send (one per category first)")
    ap.add_argument("--all", action="store_true", help="send every complaint that has a label")
    ap.add_argument("--timeout", type=int, default=120, help="seconds allowed per complaint")
    ap.add_argument("--no-probes", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    base = a.base_url.rstrip("/")
    labels = {r["complaint_id"]: r for r in read_csv(a.labels)}
    pool = [c for c in read_csv(a.complaints) if c["complaint_id"] in labels]
    if not a.all:
        rnd = random.Random()
        by_cat = {}
        for c in pool:
            by_cat.setdefault(labels[c["complaint_id"]]["category"], []).append(c)
        pick = [rnd.choice(v) for v in by_cat.values()]
        rest = [c for c in pool if c not in pick]
        pool = (pick + rnd.sample(rest, max(0, a.n - len(pick))))[: a.n]
    print(f"Sending {len(pool)} complaints to {base} (all at once), {a.timeout}s allowed each ...\n")

    with cf.ThreadPoolExecutor(max_workers=min(32, len(pool) or 1)) as ex:
        results = list(ex.map(lambda c: run_one(base, c, a.timeout), pool))

    points, crit, hits, broken, secs, hitl_ok = [], {"wrongful refund": 0, "missed fraud": 0}, {f: 0 for f in WEIGHTS}, [], [], 0
    for r in results:
        t = labels[r["id"]]
        if "error" in r:
            broken.append((r["id"], r["error"])); points.append(0); continue
        case = r["case"]; secs.append(r["seconds"])
        probs = contract_problems(case) if case.get("status") == "done" else [f"status={case.get('status')!r}"]
        if probs:
            broken.append((r["id"], "; ".join(probs)))
        got = {f: field_ok(f, str(case.get(f, "") or ""), t[f]) for f in WEIGHTS}
        for f in GATED:
            got[f] = got[f] and got["matched_txn_id"]
        for f, ok in got.items():
            hits[f] += ok
        points.append(sum(WEIGHTS[f] for f, ok in got.items() if ok))
        if (money(str(case.get("refund_amount_myr", ""))) or 0) > 0 and t["outcome"] in ("DECLINE", "INVESTIGATE"):
            crit["wrongful refund"] += 1
        if t["outcome"] == "INVESTIGATE" and str(case.get("outcome", "")).upper() != "INVESTIGATE":
            crit["missed fraud"] += 1
        route_ok = str(case.get("route", "")).upper() == t["route"]
        state_ok = state_matches_route(case)
        hitl_ok += state_ok
        print(f"{r['id']:<12} {r['seconds']:5.1f}s  {points[-1]:>3}/100  route {'ok' if route_ok else 'WRONG'}  state {'ok' if state_ok else 'WRONG'}  "
              + ", ".join(f"{f} {'ok' if ok else 'x'}" for f, ok in got.items()))
    n = len(results) or 1
    mean = sum(points) / n
    final = max(0.0, mean * (1 - 2 * sum(crit.values()) / n))
    print(f"\n{'field':<20}accuracy")
    for f in WEIGHTS:
        print(f"{f:<20}{hits[f] / n:.0%}")
    print(f"\nmean points      {mean:.1f} / 100\ncritical errors  {sum(crit.values())} {crit}\nSCORE            {final:.1f}")
    print(f"case_state and sent match the route: {hitl_ok}/{n}")
    if secs:
        q = sorted(secs)
        print(f"time per complaint: median {statistics.median(q):.1f}s, slowest {q[-1]:.1f}s")
    if broken:
        print(f"\nContract problems or failures ({len(broken)}):")
        for i, e in broken:
            print(f"  {i}: {e}")
    probe_rows = [] if a.no_probes or not pool else probes(base, pool[0]) + hitl_probes(base, results)
    if probe_rows:
        print("\nRobustness probes:")
        for name, ok, s in probe_rows:
            print(f"  [{'PASS' if ok else 'FAIL'}] {name} (HTTP {s})")
    if a.out:
        Path(a.out).write_text(json.dumps({"base_url": base, "score": round(final, 2), "mean_points": round(mean, 2), "critical": crit,
                                           "accuracy": {f: hits[f] / n for f in WEIGHTS}, "failures": broken, "state_matches_route": hitl_ok / n,
                                           "median_seconds": statistics.median(secs) if secs else None,
                                           "probes": [{"check": c, "pass": ok, "http": s} for c, ok, s in probe_rows]}, indent=2), encoding="utf-8")
        print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
