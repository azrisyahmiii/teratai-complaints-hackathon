"""Validation and normalisation of a POST /complaints body (docs/api.md)."""

from datetime import datetime
from typing import get_args

from fastapi import HTTPException
from pydantic import BaseModel

from teratai import data
from teratai.models import Channel, ComplaintRow

_CHANNELS: dict[str, Channel] = {c.lower(): c for c in get_args(Channel)}
_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S")


class ComplaintIn(BaseModel):
    complaint_id: str = ""
    customer_id: str = ""
    received_at: str = ""
    channel: str = ""
    subject: str = ""
    text: str = ""


def require_fields(body: ComplaintIn) -> None:
    for f in ("complaint_id", "customer_id", "received_at", "text"):
        if not getattr(body, f).strip():
            raise HTTPException(422, detail=f"{f} is required")


def parse_received_at(s: str) -> datetime:
    s = s.strip()
    for fmt in _FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise HTTPException(422, detail="received_at must look like 'YYYY-MM-DD HH:MM'")


def normalise_channel(raw: str) -> tuple[Channel, bool]:
    """(channel, known). Unknown or empty channels become 'App chat' (flag channel_unknown)."""
    hit = _CHANNELS.get(raw.strip().lower())
    if hit is None:
        return "App chat", False
    return hit, True


def build_row(body: ComplaintIn) -> tuple[ComplaintRow, bool]:
    """Validate customer and date, then build the Core row. Returns (row, channel_known)."""
    customer_id = body.customer_id.strip()
    if not data.has_customer(customer_id):
        raise HTTPException(422, detail=f"customer_id {customer_id} is not a known customer")
    received = parse_received_at(body.received_at)
    channel, known = normalise_channel(body.channel)
    row = ComplaintRow(
        complaint_id=body.complaint_id.strip(),
        customer_id=customer_id,
        received_at=received,
        channel=channel,
        subject=body.subject,
        text=body.text,
    )
    return row, known
