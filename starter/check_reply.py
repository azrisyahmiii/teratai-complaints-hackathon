"""The self-check every agent needs: before a reply goes anywhere, verify in code that every transaction ID and every
RM amount it mentions comes from the evidence. LLMs invent plausible numbers; this catches them.

Usage: python starter/check_reply.py CMP-00012 "We have refunded RM45.90 for transaction TXN-0001234."

In your agent, pass the complaint itself (the dict your API received, with customer_id and received_at), so the check
also works for complaints that aren't in complaints.csv, like every complaint in the live round:
    check_reply(db, complaint, reply_text)      # complaint = {"complaint_id": ..., "customer_id": ..., "received_at": ...}
"""
import datetime as dt
import re
import sys

from data import load, received


def allowed_facts(db, complaint):
    """Transaction IDs and amounts the reply may mention: the customer's transactions in the window, their reversals,
    ATM journal amounts and shortfalls, fee schedule amounts and fee overcharges, and the policy thresholds.
    `complaint` is a complaint dict (needs customer_id and received_at) or the ID of a row in complaints.csv."""
    c = db.complaints[complaint] if isinstance(complaint, str) else complaint
    recv = received(c)
    since = recv - dt.timedelta(days=int(db.params["MATCH_WINDOW_DAYS"]) + 1)
    ids, amounts = set(), {float(db.params["AUTO_REFUND_LIMIT_MYR"])}
    for t in db.txns_by_customer[c["customer_id"]]:
        if since <= t["time"] <= recv + dt.timedelta(days=1):
            ids.add(t["txn_id"]); amounts.add(round(t["amount"], 2))
            if t["txn_id"] in db.atm_journal:
                j = db.atm_journal[t["txn_id"]]
                req, disp = float(j["requested_myr"]), float(j["dispensed_myr"])
                amounts |= {req, disp, round(req - disp, 2)}
            if t["channel"] == "Fee":
                for f in db.fee_schedule:
                    amounts |= {float(f["amount_myr"]), round(t["amount"] - float(f["amount_myr"]), 2)}
    return ids, amounts


def check_reply(db, complaint, reply):
    ids, amounts = allowed_facts(db, complaint)
    problems = []
    for tid in re.findall(r"TXN-\d{7}", reply):
        if tid not in ids:
            problems.append(f"transaction {tid} is not in this customer's evidence")
    for raw in re.findall(r"RM\s?([\d,]+(?:\.\d{1,2})?)", reply):
        val = round(float(raw.replace(",", "")), 2)
        if val not in amounts:
            problems.append(f"amount RM{raw} does not appear in the evidence")
    return problems


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    db = load()
    issues = check_reply(db, sys.argv[1], sys.argv[2])
    print("VERIFIED: every ID and amount is in the evidence" if not issues else "FLAGGED:\n- " + "\n- ".join(issues))
