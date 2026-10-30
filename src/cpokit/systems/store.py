"""The enterprise systems the use cases integrate with, behind one read/write interface:

- CSMS (sites, charge points, tariffs, sessions, meter values, connector status),
- OCPI roaming (partners, CDRs),
- payments (card pre-authorisations, captures, releases),
- ERP (credit notes, refunds: written only through approved actions),
- CRM / ticketing (the work queue, drivers' tickets, partners' emails),
- document stores (the acquired network's export, the bid library).

In production each is its own system behind an API; here they share one SQLite file so a world can
be built, copied and inspected. Every read goes through `Systems`, which applies the caller's data
scope (countries, functions); the MCP servers and the use cases see nothing else."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

SCHEMA = """
create table if not exists sites (site_id text primary key, country text, city text, address text, lat real,
  lon real, tz text, vat real, lang text);
create table if not exists evses (evse_id text primary key, site_id text, kind text, kw integer);
create table if not exists tariffs (tariff_id text primary key, site_id text, kind text, valid_from integer,
  energy real, peak real, idle_per_min real, idle_grace_min integer);
create table if not exists sessions (session_id text primary key, evse_id text, site_id text, start_ts integer,
  stop_ts integer, meter_start_wh integer, meter_stop_wh integer, token text);
create index if not exists sessions_evse on sessions(evse_id, start_ts);
create index if not exists sessions_site on sessions(site_id, start_ts);
create table if not exists meter_values (session_id text, ts integer, wh integer);
create index if not exists meter_session on meter_values(session_id);
create table if not exists status_events (evse_id text, ts integer, status text, error_code text);
create index if not exists status_evse on status_events(evse_id, ts);
create table if not exists partners (partner_id text primary key, name text, lang text, country text);
create table if not exists cdrs (cdr_id text primary key, session_id text, partner_id text, evse_id text,
  site_id text, start_date_time text, end_date_time text, start_ts integer, tariff_id text,
  total_energy_kwh real, peak_energy_kwh real, idle_minutes real, energy_cost real, idle_cost real,
  total_cost_excl_vat real, vat_rate real, total_cost_incl_vat real, sent_ts integer);
create index if not exists cdrs_evse on cdrs(evse_id, start_ts);
create index if not exists cdrs_session on cdrs(session_id);
create table if not exists payments (payment_id text primary key, session_id text, evse_id text, site_id text,
  type text, amount real, ts integer, last4 text, shown_price_per_kwh real);
create index if not exists payments_session on payments(session_id);
create index if not exists payments_last4 on payments(last4, ts);
create table if not exists emails (email_id text primary key, sender text, partner_id text, subject text,
  body text, received_ts integer, lang text);
create table if not exists tickets (ticket_id text primary key, country text, lang text, channel text,
  sender text, text text, opened_ts integer);
create table if not exists cases (case_id text primary key, use_case text, ref text, country text,
  opened_ts integer, week integer);
create table if not exists site_rows (row_no integer primary key, data text);
create table if not exists site_documents (doc_id text primary key, site_code text, text text);
create table if not exists tender_docs (doc_id text primary key, title text, date text, lang text, kind text);
create table if not exists tender_passages (pid text primary key, doc_id text, text text);
create table if not exists tender_questions (question_id text primary key, lang text, text text, week integer);
create table if not exists erp_postings (posting_id text primary key, kind text, case_id text, ref text,
  amount real, currency text, payload text, approved_by text, approval_id text, posted_ts integer);
create table if not exists worklog (case_id text, user_oid text, use_case text, country text, week integer,
  minutes real, closed_ts integer, reopened integer);
create table if not exists published_locations (location_id text primary key, payload text, approved_by text,
  approval_id text, published_ts integer);
"""

TABLES = {
    "sites": ["site_id", "country", "city", "address", "lat", "lon", "tz", "vat", "lang"],
    "evses": ["evse_id", "site_id", "kind", "kw"],
    "tariffs": ["tariff_id", "site_id", "kind", "valid_from", "energy", "peak", "idle_per_min", "idle_grace_min"],
    "sessions": ["session_id", "evse_id", "site_id", "start_ts", "stop_ts", "meter_start_wh", "meter_stop_wh", "token"],
    "meter_values": ["session_id", "ts", "wh"],
    "status_events": ["evse_id", "ts", "status", "error_code"],
    "partners": ["partner_id", "name", "lang", "country"],
    "cdrs": [
        "cdr_id",
        "session_id",
        "partner_id",
        "evse_id",
        "site_id",
        "start_date_time",
        "end_date_time",
        "start_ts",
        "tariff_id",
        "total_energy_kwh",
        "peak_energy_kwh",
        "idle_minutes",
        "energy_cost",
        "idle_cost",
        "total_cost_excl_vat",
        "vat_rate",
        "total_cost_incl_vat",
        "sent_ts",
    ],
    "payments": [
        "payment_id",
        "session_id",
        "evse_id",
        "site_id",
        "type",
        "amount",
        "ts",
        "last4",
        "shown_price_per_kwh",
    ],
    "emails": ["email_id", "sender", "partner_id", "subject", "body", "received_ts", "lang"],
    "tickets": ["ticket_id", "country", "lang", "channel", "sender", "text", "opened_ts"],
    "cases": ["case_id", "use_case", "ref", "country", "opened_ts", "week"],
    "site_rows": ["row_no", "data"],
    "site_documents": ["doc_id", "site_code", "text"],
    "tender_docs": ["doc_id", "title", "date", "lang", "kind"],
    "tender_passages": ["pid", "doc_id", "text"],
    "tender_questions": ["question_id", "lang", "text", "week"],
}


class ScopeError(PermissionError):
    pass


class Systems:
    """Read access to the enterprise systems, within a data scope, and the two write paths
    (ERP postings, location publishing) that need an approval."""

    def __init__(self, path: Path | str, countries: Iterable[str] | None = None) -> None:
        self.path = str(path)
        self.countries = set(countries) if countries is not None else None
        self._local = threading.local()

    def scoped(self, countries: Iterable[str]) -> Systems:
        allowed = set(countries)
        if self.countries is not None:
            allowed &= self.countries
        return Systems(self.path, allowed)

    @property
    def db(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, check_same_thread=False)
            c.row_factory = sqlite3.Row
            self._local.conn = c
        return c

    def _rows(self, sql: str, args: Sequence[Any] = ()) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def _allowed(self, country: str | None) -> bool:
        return self.countries is None or country in self.countries

    def _site_filter(self, rows: list[dict[str, Any]], key: str = "site_id") -> list[dict[str, Any]]:
        if self.countries is None:
            return rows
        return [r for r in rows if str(r.get(key, ""))[:2] in self.countries]

    # ---- CSMS ----
    def site(self, site_id: str) -> dict[str, Any] | None:
        rows = self._site_filter(self._rows("select * from sites where site_id=?", (site_id,)))
        return rows[0] if rows else None

    def sites_matching(self, city: str | None = None, text: str | None = None) -> list[dict[str, Any]]:
        rows = self._rows("select * from sites")
        rows = [r for r in rows if self._allowed(r["country"])]
        if city:
            rows = [r for r in rows if r["city"].lower() == city.lower()]
        if text:
            t = text.lower()
            rows = [r for r in rows if r["address"].lower() in t or t in r["address"].lower()]
        return rows

    def country_tz(self, country: str) -> str | None:
        rows = self._rows("select tz from sites where country=? limit 1", (country,))
        return rows[0]["tz"] if rows else None

    def evse(self, evse_id: str) -> dict[str, Any] | None:
        rows = self._site_filter(self._rows("select * from evses where evse_id=?", (evse_id,)))
        return rows[0] if rows else None

    def evses_of(self, site_id: str) -> list[dict[str, Any]]:
        return self._site_filter(self._rows("select * from evses where site_id=?", (site_id,)))

    def tariffs(self, site_id: str, kind: str) -> list[dict[str, Any]]:
        return self._site_filter(
            self._rows("select * from tariffs where site_id=? and kind=? order by valid_from", (site_id, kind))
        )

    def session(self, session_id: str) -> dict[str, Any] | None:
        rows = self._site_filter(self._rows("select * from sessions where session_id=?", (session_id,)))
        return rows[0] if rows else None

    def sessions_near(self, evse_ids: Sequence[str], ts: int, window_s: int) -> list[dict[str, Any]]:
        if not evse_ids:
            return []
        q = ",".join("?" * len(evse_ids))
        rows = self._rows(
            f"select * from sessions where evse_id in ({q}) and start_ts between ? and ? order by start_ts",
            (*evse_ids, ts - window_s, ts + window_s),
        )
        return self._site_filter(rows)

    def meter_values(self, session_id: str) -> list[dict[str, Any]]:
        if self.session(session_id) is None:
            return []
        return self._rows("select ts, wh from meter_values where session_id=? order by ts", (session_id,))

    def status_events(self, evse_id: str, t0: int, t1: int) -> list[dict[str, Any]]:
        if self.evse(evse_id) is None:
            return []
        return self._rows(
            "select * from status_events where evse_id=? and ts between ? and ? order by ts", (evse_id, t0, t1)
        )

    # ---- OCPI ----
    def partner(self, partner_id: str) -> dict[str, Any] | None:
        rows = self._rows("select * from partners where partner_id=?", (partner_id,))
        return rows[0] if rows else None

    def cdr(self, cdr_id: str) -> dict[str, Any] | None:
        rows = self._site_filter(self._rows("select * from cdrs where cdr_id=?", (cdr_id,)))
        return rows[0] if rows else None

    def cdrs_for_session(self, session_ref: str) -> list[dict[str, Any]]:
        bare = session_ref.split("HUB-")[-1]
        return self._site_filter(
            self._rows("select * from cdrs where session_id in (?, ?) order by sent_ts", (bare, f"HUB-{bare}"))
        )

    def cdrs_near(self, evse_id: str, ts: int, window_s: int) -> list[dict[str, Any]]:
        return self._site_filter(
            self._rows(
                "select * from cdrs where evse_id=? and start_ts between ? and ? order by start_ts",
                (evse_id, ts - window_s, ts + window_s),
            )
        )

    # ---- payments ----
    def payments_for_session(self, session_id: str) -> list[dict[str, Any]]:
        return self._site_filter(self._rows("select * from payments where session_id=? order by ts", (session_id,)))

    def payments_by_card(self, last4: str, t0: int, t1: int) -> list[dict[str, Any]]:
        return self._site_filter(
            self._rows("select * from payments where last4=? and ts between ? and ? order by ts", (last4, t0, t1))
        )

    # ---- CRM ----
    def case(self, case_id: str) -> dict[str, Any] | None:
        rows = self._rows("select * from cases where case_id=?", (case_id,))
        if not rows or not self._allowed(rows[0]["country"]):
            return None
        return rows[0]

    def cases(self, use_case: str, week: int | None = None) -> list[dict[str, Any]]:
        sql, args = "select * from cases where use_case=?", [use_case]
        if week is not None:
            sql += " and week=?"
            args.append(week)
        return [r for r in self._rows(sql + " order by opened_ts", args) if self._allowed(r["country"])]

    def email(self, email_id: str) -> dict[str, Any] | None:
        rows = self._rows("select * from emails where email_id=?", (email_id,))
        return rows[0] if rows and self._allowed("DE") else None

    def ticket(self, ticket_id: str) -> dict[str, Any] | None:
        rows = self._rows("select * from tickets where ticket_id=?", (ticket_id,))
        return rows[0] if rows and self._allowed(rows[0]["country"]) else None

    # ---- documents ----
    def site_rows(self) -> list[dict[str, Any]]:
        if not self._allowed("IT"):
            return []
        return [{"row_no": r["row_no"], **json.loads(r["data"])} for r in self._rows("select * from site_rows")]

    def site_documents(self) -> list[dict[str, Any]]:
        return self._rows("select * from site_documents") if self._allowed("IT") else []

    def tender_library(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        return self._rows("select * from tender_docs"), self._rows("select * from tender_passages")

    def tender_question(self, qid: str) -> dict[str, Any] | None:
        rows = self._rows("select * from tender_questions where question_id=?", (qid,))
        return rows[0] if rows else None

    # ---- writes (only after an approval; see cpokit.approvals) ----
    def post_erp(self, posting: dict[str, Any]) -> None:
        self.db.execute(
            "insert into erp_postings values (?,?,?,?,?,?,?,?,?,?)",
            (
                posting["posting_id"],
                posting["kind"],
                posting["case_id"],
                posting["ref"],
                posting["amount"],
                posting.get("currency", "EUR"),
                json.dumps(posting.get("payload", {})),
                posting["approved_by"],
                posting["approval_id"],
                posting["posted_ts"],
            ),
        )
        self.db.commit()

    def erp_postings(self, case_id: str | None = None) -> list[dict[str, Any]]:
        if case_id:
            return self._rows("select * from erp_postings where case_id=?", (case_id,))
        return self._rows("select * from erp_postings")

    def reset_operations(self) -> None:
        """Clears what a deployment run writes (worklog, ERP postings, published locations)."""
        for t in ("worklog", "erp_postings", "published_locations"):
            self.db.execute(f"delete from {t}")
        self.db.commit()

    def log_work(self, rows: list[dict[str, Any]]) -> None:
        self.db.executemany(
            "insert into worklog values (?,?,?,?,?,?,?,?)",
            [
                (
                    r["case_id"],
                    r["user_oid"],
                    r["use_case"],
                    r["country"],
                    r["week"],
                    r["minutes"],
                    r["closed_ts"],
                    int(r.get("reopened", 0)),
                )
                for r in rows
            ],
        )
        self.db.commit()

    def worklog(self, use_case: str | None = None) -> list[dict[str, Any]]:
        rows = self._rows(
            "select * from worklog" + (" where use_case=?" if use_case else ""), (use_case,) if use_case else ()
        )
        return [r for r in rows if self._allowed(r["country"])]

    def publish_location(
        self, location_id: str, payload: dict[str, Any], approved_by: str, approval_id: str, ts: int
    ) -> None:
        self.db.execute(
            "insert or replace into published_locations values (?,?,?,?,?)",
            (location_id, json.dumps(payload), approved_by, approval_id, ts),
        )
        self.db.commit()


def create(path: Path, tables: dict[str, list[dict[str, Any]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    for name, rows in tables.items():
        cols = TABLES[name]
        con.executemany(
            f"insert into {name} ({','.join(cols)}) values ({','.join('?' * len(cols))})",
            [tuple(r.get(c) for c in cols) for r in rows],
        )
    con.commit()
    con.close()
