"""What the kit records: proposals, the actions in them, approvals, and usage events.

Usage events are append-only (a trigger refuses updates and deletes): adoption and impact are
measured from them, so nobody may rewrite them after the fact. SQLite here; `sql/kit.sql` is the
PostgreSQL version with row-level security by country."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

SCHEMA = """
create table if not exists proposals (proposal_id text primary key, case_id text, use_case text, country text,
  created_ts integer, prepared_by text, decision text, needs_review integer, payload text);
create table if not exists actions (action_id text primary key, proposal_id text, case_id text, kind text,
  amount real, payload text, payload_hash text, role text, status text, created_ts integer);
create table if not exists approvals (approval_id text primary key, action_id text, approver text, decided_ts integer,
  decision text, token_id text, consumed_ts integer);
create table if not exists usage_events (event_id integer primary key autoincrement, ts integer, use_case text,
  case_id text, country text, user_oid text, event text, value real, detail text);
create trigger if not exists usage_events_no_update before update on usage_events
  begin select raise(abort, 'usage_events is append-only'); end;
create trigger if not exists usage_events_no_delete before delete on usage_events
  begin select raise(abort, 'usage_events is append-only'); end;
create index if not exists usage_case on usage_events(case_id);
"""


class KitStore:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self.db.executescript(SCHEMA)

    @property
    def db(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, check_same_thread=False)
            c.row_factory = sqlite3.Row
            self._local.conn = c
        return c

    def rows(self, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    # proposals and actions
    def save_proposal(self, p: dict[str, Any]) -> None:
        self.db.execute(
            "insert or replace into proposals values (?,?,?,?,?,?,?,?,?)",
            (p["proposal_id"], p["case_id"], p["use_case"], p["country"], p["created_ts"], p["prepared_by"],
             p["decision"], int(p["needs_review"]), json.dumps(p, ensure_ascii=False, default=str)),
        )
        for a in p.get("actions", []):
            self.db.execute(
                "insert or replace into actions values (?,?,?,?,?,?,?,?,?,?)",
                (a["action_id"], p["proposal_id"], p["case_id"], a["kind"], a.get("amount"),
                 json.dumps(a["payload"], ensure_ascii=False, sort_keys=True), a["payload_hash"], a.get("role"),
                 a.get("status", "proposed"), p["created_ts"]),
            )
        self.db.commit()

    def proposal(self, proposal_id: str) -> dict[str, Any] | None:
        r = self.rows("select payload from proposals where proposal_id=?", (proposal_id,))
        return json.loads(r[0]["payload"]) if r else None

    def proposals(self, use_case: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        sql, args = "select payload from proposals", ()
        if use_case:
            sql, args = sql + " where use_case=?", (use_case,)
        return [json.loads(r["payload"]) for r in self.rows(sql + f" order by created_ts desc limit {int(limit)}", args)]

    def action(self, action_id: str) -> dict[str, Any] | None:
        r = self.rows("select * from actions where action_id=?", (action_id,))
        if not r:
            return None
        a = r[0]
        a["payload"] = json.loads(a["payload"])
        return a

    def set_action_status(self, action_id: str, status: str) -> None:
        self.db.execute("update actions set status=? where action_id=?", (status, action_id))
        self.db.commit()

    # approvals
    def record_approval(self, a: dict[str, Any]) -> None:
        self.db.execute(
            "insert into approvals values (?,?,?,?,?,?,?)",
            (a["approval_id"], a["action_id"], a["approver"], a["decided_ts"], a["decision"], a.get("token_id"), None),
        )
        self.db.commit()

    def consume(self, token_id: str, ts: int) -> bool:
        """Marks an approval token used; False if it was used before (or never issued)."""
        cur = self.db.execute(
            "update approvals set consumed_ts=? where token_id=? and consumed_ts is null", (ts, token_id)
        )
        self.db.commit()
        return cur.rowcount == 1

    # usage
    def event(self, ts: int, use_case: str, case_id: str, country: str, user: str, event: str,
              value: float | None = None, detail: dict[str, Any] | None = None) -> None:
        self.db.execute(
            "insert into usage_events (ts, use_case, case_id, country, user_oid, event, value, detail) "
            "values (?,?,?,?,?,?,?,?)",
            (ts, use_case, case_id, country, user, event, value, json.dumps(detail or {}, ensure_ascii=False)),
        )

    def commit(self) -> None:
        self.db.commit()

    def events(self, use_case: str | None = None) -> list[dict[str, Any]]:
        if use_case:
            return self.rows("select * from usage_events where use_case=? order by event_id", (use_case,))
        return self.rows("select * from usage_events order by event_id")
