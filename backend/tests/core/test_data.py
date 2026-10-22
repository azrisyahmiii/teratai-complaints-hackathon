import csv
import time
from datetime import date, datetime
from decimal import Decimal

from teratai import config, data


def test_txn_amount_is_decimal() -> None:
    t = data.txn("TXN-0115572")
    assert t.amount == Decimal("46.66")
    assert isinstance(t.amount, Decimal)
    assert (t.customer_id, t.merchant, t.channel) == ("CUS-00566", "GoRide", "Card e-Commerce")
    assert t.txn_time == datetime(2026, 8, 18, 10, 54, 35)
    assert t.auth_method == "3DS-OTP"
    assert data.has_txn("TXN-0115572") and not data.has_txn("TXN-9999999")


def test_reversal_lookup_both_directions() -> None:
    # TXN-0000468 (CR, Reversal) names TXN-0000193, a Failed DuitNow transfer
    rev = data.reversal_of("TXN-0000193")
    assert rev is not None
    assert rev.txn_id == "TXN-0000468"
    assert rev.direction == "CR" and rev.channel == "Reversal"
    assert rev.amount == data.txn("TXN-0000193").amount == Decimal("1103.63")
    assert data.reversal_target(rev) == "TXN-0000193"
    assert data.reversal_target(data.txn("TXN-0000193")) is None
    assert data.reversal_of("TXN-0115572") is None  # CMP-00165: neither duplicate was reversed


def test_every_reversal_resolves_to_a_txn() -> None:
    n = 0
    for t in data.txns_for("CUS-02090"):
        orig = data.reversal_target(t)
        if orig is not None:
            n += 1
            assert data.reversal_of(orig) == t
    assert n >= 1


def test_customer_and_accounts() -> None:
    c = data.customer("CUS-00566")
    assert c.full_name == "Nur Izzati binti Jamal"
    assert c.date_of_birth == date(1962, 5, 13) and c.preferred_language == "MS"
    assert next((a.account_id, a.product, a.card_last4) for a in data.accounts_for("CUS-00566")) == (
        "ACC-000896",
        "Savings Plus",
        "1662",
    )
    c2 = data.customer("CUS-02394")
    assert c2.date_of_birth == date(1994, 12, 20)
    assert data.account("ACC-003802").open_date == date(2012, 11, 7)
    assert "ACC-003802" in {a.account_id for a in data.accounts_for("CUS-02394")}
    assert data.has_customer("CUS-02394") and not data.has_customer("CUS-99999")
    assert data.accounts_for("CUS-99999") == ()


def test_txns_for_sorted_and_scoped() -> None:
    ts = data.txns_for("CUS-00566")
    assert "TXN-0115572" in {t.txn_id for t in ts}
    assert all(t.customer_id == "CUS-00566" for t in ts)
    times = [t.txn_time for t in ts]
    assert times == sorted(times)
    assert data.txns_for("CUS-99999") == ()


def test_atm_journal() -> None:
    j = data.atm_journal("TXN-0088211")
    assert j is not None
    assert (j.requested, j.dispensed) == (Decimal("1500.00"), Decimal("950.00"))
    assert j.shortfall == Decimal("550.00")
    assert data.atm_journal("TXN-0115572") is None


def test_fee_schedule() -> None:
    fees = {f.fee_code: f for f in data.fee_schedule()}
    assert len(fees) == 6
    assert fees["CC_ANNUAL_PLATINUM"].amount == Decimal("250.00")
    assert fees["MSC_BASIC"].amount == Decimal("0.00")


def test_complaints_labels_test_ids() -> None:
    assert len(data.labels()) == 1750
    assert len(data.test_ids()) == 750
    assert len(data.complaints()) == 2500
    assert set(data.labels()).isdisjoint(data.test_ids())
    c = data.complaint("CMP-00165")
    assert (c.customer_id, c.channel, c.received_at) == (
        "CUS-00566",
        "App chat",
        datetime(2026, 8, 24, 9, 25),
    )
    lab = data.labels()["CMP-00165"]
    assert (lab.matched_txn_id, lab.refund_amount, lab.route) == (
        "TXN-0115572",
        Decimal("46.66"),
        "AUTO_RESOLVE",
    )
    assert data.labels()["CMP-00244"].refund_amount == Decimal("550.00")


def test_rule_tables() -> None:
    assert data.sla_policy()["P1"].ack_hours == 2
    assert data.sla_policy()["P3"].resolve_business_days == 14
    assert "INVESTIGATE" in data.complaint_policy()["SCAM_TRANSFER"].decision_rule
    assert set(data.complaint_policy()) == set(config.CHANNEL_FAMILIES)


def test_config_defaults_equal_policy_parameters_csv() -> None:
    p = data.policy_params()
    assert config.AUTO_REFUND_LIMIT_MYR == Decimal(p["AUTO_REFUND_LIMIT_MYR"])
    assert config.VULNERABLE_AGE == int(p["VULNERABLE_AGE"])
    assert config.DEBIT_FEE_WAIVER_AGE == int(p["DEBIT_FEE_WAIVER_AGE"])
    assert config.DUPLICATE_WINDOW_MINUTES == int(p["DUPLICATE_WINDOW_MINUTES"])
    assert config.MATCH_WINDOW_DAYS == int(p["MATCH_WINDOW_DAYS"])


def test_reloading_is_idempotent_and_fast() -> None:
    data.clear_caches()
    t0 = time.perf_counter()
    data.txn("TXN-0115572")
    cold = time.perf_counter() - t0
    t1 = time.perf_counter()
    data.txn("TXN-0115572")
    warm = time.perf_counter() - t1
    print(f"cold load {cold:.2f}s, warm lookup {warm * 1e6:.0f}us")
    assert warm < 0.01
    with (config.DATA_DIR / "transactions.csv").open(encoding="utf-8") as f:
        assert len(data._txn_index().by_id) == sum(1 for _ in csv.reader(f)) - 1
