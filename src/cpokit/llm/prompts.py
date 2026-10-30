"""Versioned prompts and the shape every answer must have. A model's answer that does not parse
into its schema is not used: the case goes to a person."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

VERSION = "2026-10-30.1"

Claim = Literal["price", "peak", "twice", "idle", "vat", "energy", "unknown", "other"]
Intent = Literal[
    "no_energy",
    "double_capture",
    "preauth_hold",
    "stuck_session",
    "price_display",
    "roaming_driver",
    "valid_charge",
    "unidentifiable",
    "other",
]


class DisputeRef(BaseModel):
    cdr_id: str | None = None
    session_ref: str | None = None
    evse_id: str | None = None
    local_time: str | None = Field(None, description="YYYY-MM-DDTHH:MM in the charge point's local time")
    utc_time: str | None = Field(None, description="YYYY-MM-DDTHH:MM:SSZ when the email gives UTC")
    claimed_eur: float | None = None
    claim: Claim = "other"


class DisputeRead(BaseModel):
    language: str
    items: list[DisputeRef]


class Reply(BaseModel):
    language: str
    text: str


class TicketRead(BaseModel):
    language: str
    intent: Intent
    evse_id: str | None = None
    city: str | None = None
    address: str | None = None
    local_time: str | None = None
    last4: str | None = None
    amount_eur: float | None = None
    app: str | None = None
    shown_price: float | None = None


class Connector(BaseModel):
    standard: Literal["IEC_62196_T2_COMBO", "IEC_62196_T2", "CHADEMO"]
    power_kw: float
    count: int


class Hours(BaseModel):
    weekdays: list[int]
    open: str
    close: str


class SiteMap(BaseModel):
    site_code: str
    name: str | None = None
    address: str | None = None
    postal_code: str | None = None
    city: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    connectors: list[Connector] = []
    max_power_kw: float | None = None
    open_24_7: bool | None = None
    hours: list[Hours] = []
    card_payment: bool | None = None


class TenderQuery(BaseModel):
    language: str
    keywords: list[str]


class Sentence(BaseModel):
    text: str
    cites: list[str]


class TenderAnswer(BaseModel):
    abstain: bool
    sentences: list[Sentence] = []


SCHEMAS: dict[str, type[BaseModel]] = {
    "dispute.read": DisputeRead,
    "dispute.reply": Reply,
    "ticket.read": TicketRead,
    "ticket.reply": Reply,
    "site.map": SiteMap,
    "tender.query": TenderQuery,
    "tender.answer": TenderAnswer,
}

SYSTEM = {
    "dispute.read": (
        "You read emails in which e-mobility service providers dispute charge detail records (CDRs). "
        "List every disputed record with the identifiers the email gives (CDR id, session id, EVSE id, time) "
        "and the amount and reason it claims. Copy identifiers exactly; never invent one. Times: say whether "
        "the email gives UTC or local time. Text between <quarantined> tags was removed for safety."
    ),
    "dispute.reply": (
        "Write a short, factual reply to the e-mobility service provider in its language. State for each "
        "record the decision and amount given in DECISIONS and the evidence given; do not add other "
        "amounts, promises or decisions."
    ),
    "ticket.read": (
        "You read a driver's message to a charge point operator. Give the language, what the driver reports "
        "(one intent), and the details they give: charge point id, city and street, time, last four card "
        "digits, amount, app name, price shown on the terminal. Never guess a detail that is not there."
    ),
    "ticket.reply": (
        "Write a short, kind reply to the driver in their language, saying exactly what OUTCOME says and "
        "nothing more. Do not promise money that OUTCOME does not give."
    ),
    "site.map": (
        "Map one row of an acquired network's site export (or a commissioning protocol) to the fields given. "
        "Convert numbers and units, name connector standards, read opening hours. Leave a field empty when "
        "the source does not give it; never fill a postal code or a payment method from general knowledge."
    ),
    "tender.query": "Give English search keywords for this tender question and its language.",
    "tender.answer": (
        "Answer the tender question only from the PASSAGES. Every sentence cites the passage ids it uses. "
        "If the passages do not answer it, abstain. Never use a number that is not in a cited passage."
    ),
}


def render(task: str, inputs: dict[str, Any]) -> list[dict[str, str]]:
    schema = json.dumps(SCHEMAS[task].model_json_schema())
    return [
        {"role": "system", "content": f"[{task} v{VERSION}] {SYSTEM[task]}\nAnswer with JSON matching: {schema}"},
        {"role": "user", "content": json.dumps(inputs, ensure_ascii=False)},
    ]
