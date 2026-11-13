"""Authoritative workbench items, approvals and private artifacts."""

from __future__ import annotations

import json
import uuid
from contextlib import closing
from pathlib import Path

from app.atomic import atomic_write_text
from app.database import WORKSPACE_REGISTRY, apply_migrations, connect_database
from app.plugin_paths import plugin_root

ANSWER_REFERENCE = "workbench-answer:"
SCHEMA = """
CREATE TABLE workflow_items (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL
);
CREATE TABLE workflow_turns (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL REFERENCES workflow_items(id),
    objective TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL,
    fingerprint TEXT NOT NULL DEFAULT '',
    previous_id TEXT REFERENCES workflow_turns(id),
    card INTEGER UNIQUE,
    choice INTEGER,
    delivered INTEGER NOT NULL DEFAULT 0,
    run INTEGER UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX workflow_single_active ON workflow_turns(item_id)
WHERE state IN ('approved','running');
"""


def identifier() -> str:
    return uuid.uuid4().hex


class WorkflowStore:
    def __init__(self, root: Path):
        self.path = root / "workspace.db"
        self.root = plugin_root(root)
        apply_migrations(
            self.path, registry=WORKSPACE_REGISTRY, subsystem="workflow",
            migrations={1: SCHEMA, 2: "ALTER TABLE workflow_turns ADD COLUMN has_answer INTEGER NOT NULL DEFAULT 0;"},
            snapshot_root=root / "working" / "db-migrations",
        )

    def _query(self, sql, values=()):
        with closing(connect_database(self.path)) as db:
            return [dict(row) for row in db.execute(sql, values).fetchall()]

    def _write(self, sql, values=()):
        with closing(connect_database(self.path)) as db, db:
            return db.execute(sql, values).rowcount

    def archive(self):
        path = self.root / "workflow-archive.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def item_archived(self, item_id):
        return item_id in self.archive().get("items", ())

    def item(self, item_id):
        return next(iter(self._query("SELECT * FROM workflow_items WHERE id=?", (item_id,))), None)

    def handoff(self, source: str, title: str) -> str:
        title = title.strip()
        if not title or len(title) > 200:
            raise ValueError("任务标题须为 1–200 字")
        if archive_time := self.archive().get("time"):
            source = f"{archive_time}:{source}"
        self._write("INSERT OR IGNORE INTO workflow_items VALUES (?, ?, ?)", (identifier(), source, title))
        return self._query("SELECT id FROM workflow_items WHERE source=?", (source,))[0]["id"]

    def turns(self, item_id):
        return self._query("SELECT * FROM workflow_turns WHERE item_id=? ORDER BY rowid DESC", (item_id,))

    def turn(self, turn_id):
        return next(iter(self._query("SELECT * FROM workflow_turns WHERE id=?", (turn_id,))), None)

    def payload(self, turn_id: str) -> dict:
        return json.loads((self.root / "results" / f"{turn_id}.json").read_text())

    def save_telemetry(self, turn_id: str, events: list[dict]) -> None:
        atomic_write_text(self.root / "results" / f"{turn_id}.telemetry.json", json.dumps(events))

    def telemetry(self, turn_id: str) -> list[dict]:
        try:
            events = json.loads((self.root / "results" / f"{turn_id}.telemetry.json").read_text())
        except (OSError, ValueError):
            return []
        if not isinstance(events, list):
            return []
        return [
            {key: event[key] for key in ("type", "at", "outcome") if key in event}
            for event in events[:32]
            if isinstance(event, dict) and event.get("type") in ("session.ready", "agent.finish")
            and type(event.get("at")) is int and event.get("outcome") in (None, "completed", "interrupted")
        ]

    def answer_path(self, turn_id):
        return self.root / "results" / f"{turn_id}.answer.txt"

    def private_answer(self, turn):
        return self.answer_path(turn["id"]).read_text() if turn["has_answer"] else ""

    def resolve_answer(self, card, answer):
        if not answer or not answer.startswith(ANSWER_REFERENCE):
            return answer
        ref = answer.removeprefix(ANSWER_REFERENCE)
        rows = self._query("SELECT id, has_answer FROM workflow_turns WHERE card=? AND id=?", (card, ref))
        if not rows:
            return answer
        try:
            return self.private_answer(rows[0]) or None
        except OSError:
            return None

    def active_items(self):
        return self._query("""
            SELECT i.id, i.title, i.source, t.state, t.run, t.id AS turn
            FROM workflow_items i LEFT JOIN workflow_turns t ON t.id=(
                SELECT id FROM workflow_turns WHERE item_id=i.id ORDER BY rowid DESC LIMIT 1)
            WHERE i.id NOT IN (SELECT value FROM json_each(?))
            ORDER BY i.rowid DESC
        """, (json.dumps(self.archive().get("items", [])),))

    def turn_links(self):
        return self._query("""
            SELECT t.id, t.item_id, t.run, p.run AS previous_run FROM workflow_turns t
            LEFT JOIN workflow_turns p ON p.id=t.previous_id
        """)

    def save_approval(self, item_id, objective, previous, card, choice, fingerprint, answer_text):
        turn_id = identifier()
        reply = answer_text.strip()
        answer_path = self.answer_path(turn_id) if reply else None
        try:
            with closing(connect_database(self.path)) as db, db:
                db.execute("BEGIN IMMEDIATE")
                latest = db.execute(
                    "SELECT id FROM workflow_turns WHERE item_id=? ORDER BY rowid DESC LIMIT 1", (item_id,),
                ).fetchone()
                if (latest["id"] if latest else None) != (previous["id"] if previous else None):
                    raise ValueError("任务已有新一轮，请刷新")
                if answer_path is not None:
                    atomic_write_text(answer_path, reply)
                db.execute(
                    """INSERT INTO workflow_turns(id,item_id,objective,state,fingerprint,previous_id,card,choice,has_answer)
                       VALUES (?,?,?,'approved',?,?,?,?,?)""",
                    (turn_id, item_id, objective.strip(), fingerprint, previous["id"] if previous else None,
                     card, choice, int(bool(reply))),
                )
        except Exception:
            if answer_path is not None:
                answer_path.unlink(missing_ok=True)
            raise

    def pending_dispatch(self):
        return self._query("""
            SELECT t.* FROM workflow_turns t JOIN workflow_items i ON t.item_id=i.id
            WHERE t.state='approved' AND t.delivered=0
                AND i.id NOT IN (SELECT value FROM json_each(?))
            ORDER BY t.rowid
        """, (json.dumps(self.archive().get("items", [])),))

    def mark_delivered(self, turn_id):
        self._write("UPDATE workflow_turns SET delivered=1 WHERE id=?", (turn_id,))

    def fail_dispatch(self, turn_id):
        self._write(
            "UPDATE workflow_turns SET state='failed' WHERE id=? AND state='approved'", (turn_id,),
        )

    def linked_turn(self, run_id):
        return next(iter(self._query("SELECT * FROM workflow_turns WHERE run=?", (run_id,))), None)

    def approved_card_turn(self, card_id):
        return next(iter(self._query(
            "SELECT * FROM workflow_turns WHERE card=? AND state='approved'", (card_id,),
        )), None)

    def create_pending_turn(self, run_id, title):
        item_id = self.handoff(f"engine:{run_id}", title)
        turn_id = identifier()
        self._write(
            "INSERT INTO workflow_turns(id,item_id,state,run) VALUES (?,?,'approval',?)",
            (turn_id, item_id, run_id),
        )
        return self.turn(turn_id)

    def start_approved_turn(self, turn_id, run_id):
        return self._write(
            "UPDATE workflow_turns SET state='running',run=?,delivered=1 WHERE id=? AND state='approved'",
            (run_id, turn_id),
        )

    def save_candidate(self, turn_id, candidate):
        atomic_write_text(self.root / "results" / f"{turn_id}.json", json.dumps(candidate, ensure_ascii=False))

    def finish_running_turn(self, turn_id, state):
        self._write("UPDATE workflow_turns SET state=? WHERE id=? AND state='running'", (state, turn_id))
        return self.turn(turn_id)["state"]

    def recover_interrupted_turns(self):
        for turn in self._query("SELECT id FROM workflow_turns WHERE state='running'"):
            try:
                candidate = self.payload(turn["id"])
                if isinstance(candidate, dict) and "draft" in candidate:
                    state = "draft"
                elif isinstance(candidate, dict) and {"question", "options"} <= candidate.keys():
                    state = "decision"
                else:
                    state = "failed"
            except (OSError, ValueError):
                state = "failed"
            self.finish_running_turn(turn["id"], state)

    def accept(self, item_id, turn_id):
        return not self.item_archived(item_id) and self._write(
            "UPDATE workflow_turns SET state='accepted' WHERE id=? AND item_id=? AND state='draft'",
            (turn_id, item_id),
        )

    def cancel(self, run_id, approved_events, cards):
        with closing(connect_database(self.path)) as db, db:
            db.execute(
                "UPDATE workflow_turns SET state='cancelled' WHERE run=? AND state IN ('approved','running')",
                (run_id,),
            )
            db.executemany(
                "UPDATE workflow_turns SET state='cancelled' WHERE id=? AND item_id=? AND state='approved'",
                approved_events,
            )
            db.executemany(
                "UPDATE workflow_turns SET state='cancelled' WHERE card=? AND state='approved'",
                ((card_id,) for card_id in cards),
            )
