"""Tool registry (SPEC §4.4b, §13): the lookups the matcher and the investigator share.

Two layers:
- typed functions (`find_transactions`, ...) return dataclasses; `match.py` calls them directly;
- `TOOLS` maps a tool name to a JSON schema + a handler taking the model's JSON args and returning a
  JSON-able dict (money as strings). `tool_specs()` / `handlers(customer_id)` plug straight into
  `LLMProvider.tool_loop`; the handlers are bound to the case customer and answer {"error": "out of scope"}
  for any other customer, transaction or account.

No file I/O here: everything goes through `teratai.data`. The LLM only reads through these tools; code
validates whatever it concludes.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from teratai import config, data
from teratai.data import Txn

Args = dict[str, Any]
Handler = Callable[[Args], dict[str, Any]]


# --- typed lookups ---------------------------------------------------------------------------------


def amount_matches(
    txn_amount: Decimal, amount: Decimal, approx: bool = False, tol: Decimal | None = None
) -> bool:
    """Exact: |a - b| <= tol (default 0.005). Approximate: within max(5%, RM20) (SPEC §4.4)."""
    if tol is None:
        tol = (
            max(amount * config.AMOUNT_APPROX_PCT, config.AMOUNT_APPROX_MIN_MYR)
            if approx
            else config.AMOUNT_EXACT_TOL
        )
    return abs(txn_amount - amount) <= tol


def find_transactions(
    customer_id: str,
    start: date,
    end: date,
    channels: Iterable[str],
    direction: str = "DR",
    amount: Decimal | None = None,
    tol: Decimal | None = None,
    card_last4: str | None = None,
    description_prefix: str | None = None,
) -> list[Txn]:
    """The matcher's hard filters: customer, inclusive date window, channel family, direction, amount, card.

    `tol=None` means exact (±0.005). Sorted oldest first.
    """
    chans = set(channels)
    out: list[Txn] = []
    for t in data.txns_for(customer_id):
        if t.direction != direction or t.channel not in chans:
            continue
        if not (start <= t.txn_time.date() <= end):
            continue
        if amount is not None and not amount_matches(t.amount, amount, tol=tol):
            continue
        if card_last4 and t.card_last4 != card_last4:
            continue
        if description_prefix and not t.description.startswith(description_prefix):
            continue
        out.append(t)
    return out


def owned_card_last4(customer_id: str) -> set[str]:
    """Card numbers (last 4) on the customer's accounts or seen on their transactions."""
    owned = {a.card_last4 for a in data.accounts_for(customer_id) if a.card_last4}
    owned |= {t.card_last4 for t in data.txns_for(customer_id) if t.card_last4}
    return owned


# --- JSON views ------------------------------------------------------------------------------------


def txn_view(t: Txn) -> dict[str, str]:
    """A transaction as the model sees it. Money is a string."""
    return {
        "txn_id": t.txn_id,
        "txn_time": t.txn_time.isoformat(sep=" "),
        "account_id": t.account_id,
        "direction": t.direction,
        "amount_myr": str(t.amount),
        "channel": t.channel,
        "merchant_or_counterparty": t.merchant,
        "card_last4": t.card_last4,
        "auth_method": t.auth_method,
        "status": t.status,
        "description": t.description,
    }


MAX_RESULTS = 25  # keep the tool output small for the model


def _need(args: Args, key: str) -> Any:
    if key not in args or args[key] in (None, ""):
        raise ValueError(f"missing argument: {key}")
    return args[key]


def _h_find_transactions(args: Args) -> dict[str, Any]:
    customer_id = str(_need(args, "customer_id"))
    if not data.has_customer(customer_id):
        return {"error": f"unknown customer {customer_id}"}
    amount = Decimal(str(args["amount"])) if args.get("amount") not in (None, "") else None
    tol = Decimal(str(args["tol"])) if args.get("tol") not in (None, "") else None
    found = find_transactions(
        customer_id,
        date.fromisoformat(str(_need(args, "start"))),
        date.fromisoformat(str(_need(args, "end"))),
        list(args.get("channels") or []),
        direction=str(args.get("direction") or "DR"),
        amount=amount,
        tol=tol,
        card_last4=args.get("card_last4") or None,
        description_prefix=args.get("description_prefix") or None,
    )
    return {"count": len(found), "transactions": [txn_view(t) for t in found[:MAX_RESULTS]]}


def _h_get_customer(args: Args) -> dict[str, Any]:
    cid = str(_need(args, "customer_id"))
    if not data.has_customer(cid):
        return {"error": f"unknown customer {cid}"}
    c = data.customer(cid)
    return {
        "customer_id": c.customer_id,
        "full_name": c.full_name,
        "date_of_birth": c.date_of_birth.isoformat(),
        "preferred_language": c.preferred_language,
        "segment": c.segment,
        "customer_since": c.customer_since.isoformat(),
    }


def _h_get_accounts(args: Args) -> dict[str, Any]:
    cid = str(_need(args, "customer_id"))
    return {
        "accounts": [
            {
                "account_id": a.account_id,
                "product": a.product,
                "open_date": a.open_date.isoformat(),
                "card_last4": a.card_last4,
            }
            for a in data.accounts_for(cid)
        ]
    }


def _h_get_atm_journal(args: Args) -> dict[str, Any]:
    tid = str(_need(args, "txn_id"))
    j = data.atm_journal(tid)
    if j is None:
        return {"error": f"no ATM journal for {tid}"}
    return {
        "txn_id": j.txn_id,
        "atm_location": j.atm_location,
        "requested_myr": str(j.requested),
        "dispensed_myr": str(j.dispensed),
        "shortfall_myr": str(j.shortfall),
        "journal_status": j.journal_status,
    }


def _h_get_reversal(args: Args) -> dict[str, Any]:
    tid = str(_need(args, "txn_id"))
    r = data.reversal_of(tid)
    if r is None:
        return {"reversal": None}
    return {"reversal": txn_view(r)}


def _h_get_fee_schedule(_args: Args) -> dict[str, Any]:
    return {
        "fees": [
            {
                "fee_code": f.fee_code,
                "fee_name": f.fee_name,
                "product": f.product,
                "amount_myr": str(f.amount),
                "waiver_rule": f.waiver_rule,
            }
            for f in data.fee_schedule()
        ]
    }


def _obj(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


_CUSTOMER = {"customer_id": {"type": "string", "description": "e.g. CUS-01234"}}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Handler


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in (
        Tool(
            "find_transactions",
            "List a customer's transactions in an inclusive date window, filtered by channel, direction and "
            "optionally amount (exact unless tol is given) or card last 4.",
            _obj(
                {
                    **_CUSTOMER,
                    "start": {"type": "string", "description": "YYYY-MM-DD, inclusive"},
                    "end": {"type": "string", "description": "YYYY-MM-DD, inclusive"},
                    "channels": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "Card POS",
                                "Card e-Commerce",
                                "DuitNow Transfer",
                                "IBG Transfer",
                                "ATM Withdrawal",
                                "Fee",
                            ],
                        },
                    },
                    "direction": {"type": "string", "enum": ["DR", "CR"], "default": "DR"},
                    "amount": {"type": "string", "description": "RM amount, e.g. 46.66"},
                    "tol": {"type": "string", "description": "absolute tolerance in RM around amount"},
                    "card_last4": {"type": "string"},
                    "description_prefix": {"type": "string", "description": "e.g. 'Monthly service charge'"},
                },
                ["customer_id", "start", "end", "channels"],
            ),
            _h_find_transactions,
        ),
        Tool(
            "get_customer",
            "Customer profile (name, date of birth, language).",
            _obj(_CUSTOMER, ["customer_id"]),
            _h_get_customer,
        ),
        Tool(
            "get_accounts",
            "The customer's accounts, products and card last 4.",
            _obj(_CUSTOMER, ["customer_id"]),
            _h_get_accounts,
        ),
        Tool(
            "get_atm_journal",
            "What the ATM recorded for an ATM Withdrawal: requested vs dispensed cash.",
            _obj({"txn_id": {"type": "string"}}, ["txn_id"]),
            _h_get_atm_journal,
        ),
        Tool(
            "get_reversal",
            "The reversal credit that refunds a transaction, if one exists.",
            _obj({"txn_id": {"type": "string"}}, ["txn_id"]),
            _h_get_reversal,
        ),
        Tool("get_fee_schedule", "The bank's fee schedule.", _obj({}, []), _h_get_fee_schedule),
    )
}


def tool_specs() -> list[dict[str, Any]]:
    """Tool definitions in the shape `LLMProvider.tool_loop(tools=...)` takes."""
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in TOOLS.values()
    ]


OUT_OF_SCOPE: dict[str, Any] = {"error": "out of scope"}


def _in_scope(args: Args, customer_id: str) -> bool:
    """A call may only touch the case customer's own data (SPEC §4.4b: code bounds what the model can read)."""
    if args.get("customer_id") not in (None, "", customer_id):
        return False
    tid = args.get("txn_id")
    if tid not in (None, "") and (not data.has_txn(str(tid)) or data.txn(str(tid)).customer_id != customer_id):
        return False
    aid = args.get("account_id")
    return aid in (None, "") or str(aid) in {a.account_id for a in data.accounts_for(customer_id)}


def _scoped(tool: Tool, customer_id: str) -> Handler:
    def run(args: Args) -> dict[str, Any]:
        if not _in_scope(args, customer_id):
            return dict(OUT_OF_SCOPE)
        if "customer_id" in tool.input_schema["properties"]:
            args = {**args, "customer_id": customer_id}  # the model may leave it out: it is always the case's
        return tool.handler(args)

    return run


def handlers(customer_id: str) -> dict[str, Handler]:
    """Name -> handler map for `LLMProvider.tool_loop(handlers=...)`, bound to one case's customer."""
    return {t.name: _scoped(t, customer_id) for t in TOOLS.values()}


def call_tool(name: str, args: Args, customer_id: str) -> dict[str, Any]:
    """Run a tool by name for the case customer. Bad arguments come back as {"error": ...} so the model can retry."""
    tool = TOOLS.get(name)
    if tool is None:
        return {"error": f"unknown tool {name}"}
    try:
        return _scoped(tool, customer_id)(args)
    except (ValueError, ArithmeticError, TypeError) as e:
        return {"error": str(e)}
