"""Private, manually maintained phase goals and weekly execution state."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse
from uuid import uuid4

from app.database import WORKSPACE_REGISTRY, apply_migrations, connect_database
from app.workspace import SHANGHAI


FOCUS_STATUSES = {
    "planned": "计划中",
    "active": "进行中",
    "blocked": "受阻",
    "done": "完成",
    "paused": "暂缓",
}
FOCUS_AREAS = {"venture", "career", "life", "creation", "learning", "admin"}
FOCUS_PRIORITIES = {"P0", "P1", "P2"}
FOCUS_VISIBILITIES = {"overview", "detail_only"}
FOCUS_MODULES = {"", "career", "learning", "articles", "income", "reviews"}


def _now() -> str:
    return datetime.now(SHANGHAI).replace(microsecond=0).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def _date(value: str, *, required: bool = False) -> str:
    value = value.strip()
    if not value and not required:
        return ""
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise ValueError("日期必须为 YYYY-MM-DD") from error


def week_start(value: date) -> str:
    return (value - timedelta(days=value.weekday())).isoformat()


def _text(value: object, label: str, maximum: int = 180) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"{label}不能为空")
    if len(cleaned) > maximum:
        raise ValueError(f"{label}不能超过 {maximum} 字")
    return cleaned


def _external_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("协作链接必须是 HTTPS 地址")
    return value[:1000]


@dataclass(frozen=True)
class FocusCycle:
    id: str
    key: str
    title: str
    starts_on: str
    ends_on: str
    created_at: str


@dataclass(frozen=True)
class FocusGoal:
    id: str
    cycle_id: str
    title: str
    summary: str
    area: str
    priority: str
    status: str
    target_on: str
    visibility: str
    module_key: str
    external_url: str
    sort_order: int
    updated_at: str


@dataclass(frozen=True)
class FocusDeliverable:
    id: str
    goal_id: str
    title: str
    due_on: str
    status: str
    week_focus_on: str
    updated_at: str


@dataclass(frozen=True)
class FocusAction:
    id: str
    deliverable_id: str
    title: str
    due_on: str
    status: str
    day_focus_on: str
    updated_at: str


@dataclass(frozen=True)
class DailyEvent:
    id: str
    title: str
    due_on: str
    status: str
    updated_at: str


@dataclass(frozen=True)
class FocusDecision:
    id: str
    cycle_id: str
    title: str
    due_on: str
    question: str
    status: str


@dataclass(frozen=True)
class FocusCheckin:
    cycle_id: str
    week_start_on: str
    completed: str
    friction: str
    next_three: str
    updated_at: str


SCHEMA = """
CREATE TABLE focus_cycles (
    id TEXT PRIMARY KEY, key TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
    starts_on TEXT NOT NULL, ends_on TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE focus_goals (
    id TEXT PRIMARY KEY, cycle_id TEXT NOT NULL REFERENCES focus_cycles(id) ON DELETE CASCADE,
    title TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '', area TEXT NOT NULL,
    priority TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'planned',
    target_on TEXT NOT NULL DEFAULT '', visibility TEXT NOT NULL DEFAULT 'overview',
    module_key TEXT NOT NULL DEFAULT '', external_url TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL
);
CREATE INDEX focus_goals_cycle_idx ON focus_goals(cycle_id, sort_order);
CREATE TABLE focus_deliverables (
    id TEXT PRIMARY KEY, goal_id TEXT NOT NULL REFERENCES focus_goals(id) ON DELETE CASCADE,
    title TEXT NOT NULL, due_on TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'planned', week_focus_on TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
CREATE INDEX focus_deliverables_goal_idx ON focus_deliverables(goal_id, due_on);
CREATE TABLE focus_actions (
    id TEXT PRIMARY KEY, deliverable_id TEXT NOT NULL REFERENCES focus_deliverables(id) ON DELETE CASCADE,
    title TEXT NOT NULL, due_on TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'planned', day_focus_on TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
CREATE INDEX focus_actions_deliverable_idx ON focus_actions(deliverable_id, due_on);
CREATE TABLE focus_decisions (
    id TEXT PRIMARY KEY, cycle_id TEXT NOT NULL REFERENCES focus_cycles(id) ON DELETE CASCADE,
    title TEXT NOT NULL, due_on TEXT NOT NULL, question TEXT NOT NULL DEFAULT ''
);
CREATE TABLE focus_checkins (
    cycle_id TEXT NOT NULL REFERENCES focus_cycles(id) ON DELETE CASCADE,
    week_start_on TEXT NOT NULL, completed TEXT NOT NULL DEFAULT '',
    friction TEXT NOT NULL DEFAULT '', next_three TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL, PRIMARY KEY(cycle_id, week_start_on)
);
"""
SCHEMA_V2 = "ALTER TABLE focus_decisions ADD COLUMN status TEXT NOT NULL DEFAULT 'planned';"
SCHEMA_V3 = """CREATE TABLE daily_events (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, due_on TEXT NOT NULL,
    status TEXT NOT NULL, updated_at TEXT NOT NULL
);"""


SCHEMA_V4 = """
CREATE TABLE planner_slots (
    event_id TEXT PRIMARY KEY, day TEXT NOT NULL,
    minute INTEGER CHECK(minute IS NULL OR (minute BETWEEN 0 AND 1410 AND minute % 30 = 0))
);
CREATE INDEX planner_slots_day ON planner_slots(day);
CREATE TABLE planner_activity (
    id INTEGER PRIMARY KEY, event_id TEXT NOT NULL, action TEXT NOT NULL, occurred_at TEXT NOT NULL
);
CREATE INDEX planner_activity_time ON planner_activity(occurred_at);
"""


def planner_slot(day: str, time: str) -> tuple[str, int | None]:
    day = _date(day, required=True)
    if not 2 <= date.fromisoformat(day).year <= 9998:
        raise ValueError("安排日期超出日历范围")
    if not time:
        return day, None
    if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):(?:00|30)", time):
        raise ValueError("开始时间请选择整点或半点")
    return day, int(time[:2]) * 60 + int(time[3:])


def planner_slot_key(slot: tuple[str, int | None] | None) -> str:
    if slot is None:
        return ""
    return f"{slot[0]}/{slot[1] if slot[1] is not None else ''}"


def record_planner_activity(connection: sqlite3.Connection, event_id: str, action: str) -> None:
    connection.execute(
        "INSERT INTO planner_activity(event_id, action, occurred_at) VALUES (?, ?, ?)",
        (event_id, action, _now()),
    )


class FocusRepository:
    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root
        self.database_path = data_root / "workspace.db"
        apply_migrations(
            self.database_path,
            registry=WORKSPACE_REGISTRY,
            subsystem="focus",
            migrations={1: SCHEMA, 2: SCHEMA_V2, 3: SCHEMA_V3, 4: SCHEMA_V4},
            snapshot_root=data_root / "working" / "db-migrations",
        )

    def connect(self) -> sqlite3.Connection:
        return connect_database(self.database_path)

    def _rows(self, sql: str, cls: type, params: tuple = ()) -> tuple:
        with self.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return tuple(cls(**dict(row)) for row in rows)

    def cycles(self) -> tuple[FocusCycle, ...]:
        return self._rows("SELECT * FROM focus_cycles ORDER BY starts_on DESC", FocusCycle)

    def current_cycle(self, today: date | None = None) -> FocusCycle | None:
        cycles = self.cycles()
        if not cycles:
            return None
        today = today or datetime.now(SHANGHAI).date()
        return next((row for row in cycles if row.starts_on <= today.isoformat() <= row.ends_on), cycles[0])

    def cycle(self, cycle_id: str) -> FocusCycle | None:
        rows = self._rows("SELECT * FROM focus_cycles WHERE id=?", FocusCycle, (cycle_id,))
        return rows[0] if rows else None

    def create_cycle(self, *, key: str, title: str, starts_on: str, ends_on: str) -> FocusCycle:
        key = _text(key, "阶段标识", 100)
        title = _text(title, "阶段名称")
        start, end = _date(starts_on, required=True), _date(ends_on, required=True)
        if end < start:
            raise ValueError("结束日期不能早于开始日期")
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM focus_cycles WHERE key=?", (key,)).fetchone()
            if row:
                return FocusCycle(**dict(row))
            cycle = FocusCycle(_id("cycle"), key, title, start, end, _now())
            connection.execute("INSERT INTO focus_cycles VALUES(?,?,?,?,?,?)", tuple(cycle.__dict__.values()))
        return cycle

    def goals(self, cycle_id: str) -> tuple[FocusGoal, ...]:
        return self._rows(
            "SELECT * FROM focus_goals WHERE cycle_id=? ORDER BY sort_order, priority, target_on, title",
            FocusGoal, (cycle_id,),
        )

    def goal(self, goal_id: str) -> FocusGoal | None:
        rows = self._rows("SELECT * FROM focus_goals WHERE id=?", FocusGoal, (goal_id,))
        return rows[0] if rows else None

    def create_goal(self, *, cycle_id: str, title: str, area: str, priority: str,
                    summary: str = "", target_on: str = "", visibility: str = "overview",
                    module_key: str = "", external_url: str = "", sort_order: int = 0) -> FocusGoal:
        if self.cycle(cycle_id) is None:
            raise ValueError("阶段不存在")
        if area not in FOCUS_AREAS or priority not in FOCUS_PRIORITIES:
            raise ValueError("领域或优先级无效")
        if visibility not in FOCUS_VISIBILITIES or module_key not in FOCUS_MODULES:
            raise ValueError("可见范围或模块无效")
        goal = FocusGoal(
            _id("goal"), cycle_id, _text(title, "目标"), str(summary).strip()[:500],
            area, priority, "planned", _date(target_on), visibility, module_key,
            _external_url(external_url), int(sort_order), _now(),
        )
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO focus_goals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                tuple(goal.__dict__.values()),
            )
        return goal

    def update_goal(self, goal_id: str, *, title: str, summary: str, target_on: str,
                    status: str, external_url: str, area: str | None = None,
                    priority: str | None = None, visibility: str | None = None,
                    module_key: str | None = None) -> FocusGoal:
        current = self.goal(goal_id)
        if current is None:
            raise KeyError(goal_id)
        if status not in FOCUS_STATUSES:
            raise ValueError("状态无效")
        area = current.area if area is None else area
        priority = current.priority if priority is None else priority
        visibility = current.visibility if visibility is None else visibility
        module_key = current.module_key if module_key is None else module_key
        if area not in FOCUS_AREAS or priority not in FOCUS_PRIORITIES:
            raise ValueError("领域或优先级无效")
        if visibility not in FOCUS_VISIBILITIES or module_key not in FOCUS_MODULES:
            raise ValueError("可见范围或模块无效")
        values = (_text(title, "目标"), summary.strip()[:500], _date(target_on),
                  status, _external_url(external_url), area, priority, visibility,
                  module_key, _now(), goal_id)
        with self.connect() as connection:
            connection.execute(
                "UPDATE focus_goals SET title=?,summary=?,target_on=?,status=?,external_url=?,"
                "area=?,priority=?,visibility=?,module_key=?,updated_at=? WHERE id=?",
                values,
            )
            if visibility == "detail_only":
                connection.execute(
                    "UPDATE focus_deliverables SET week_focus_on='' WHERE goal_id=?", (goal_id,)
                )
                connection.execute(
                    "UPDATE focus_actions SET day_focus_on='' WHERE deliverable_id IN "
                    "(SELECT id FROM focus_deliverables WHERE goal_id=?)", (goal_id,),
                )
        return self.goal(goal_id)  # type: ignore[return-value]

    def deliverables(self, goal_id: str) -> tuple[FocusDeliverable, ...]:
        return self._rows(
            "SELECT * FROM focus_deliverables WHERE goal_id=? ORDER BY due_on, title",
            FocusDeliverable, (goal_id,),
        )

    def cycle_deliverables(self, cycle_id: str) -> tuple[FocusDeliverable, ...]:
        return self._rows(
            "SELECT d.* FROM focus_deliverables d JOIN focus_goals g ON g.id=d.goal_id "
            "WHERE g.cycle_id=? ORDER BY d.due_on, d.title",
            FocusDeliverable, (cycle_id,),
        )

    def deliverable(self, deliverable_id: str) -> FocusDeliverable | None:
        rows = self._rows("SELECT * FROM focus_deliverables WHERE id=?", FocusDeliverable, (deliverable_id,))
        return rows[0] if rows else None

    def create_deliverable(self, *, goal_id: str, title: str, due_on: str = "") -> FocusDeliverable:
        if self.goal(goal_id) is None:
            raise ValueError("目标不存在")
        row = FocusDeliverable(_id("deliverable"), goal_id, _text(title, "交付物"),
                               _date(due_on), "planned", "", _now())
        with self.connect() as connection:
            connection.execute("INSERT INTO focus_deliverables VALUES(?,?,?,?,?,?,?)", tuple(row.__dict__.values()))
        return row

    def update_deliverable(self, deliverable_id: str, *, title: str, due_on: str, status: str) -> FocusDeliverable:
        if self.deliverable(deliverable_id) is None:
            raise KeyError(deliverable_id)
        if status not in FOCUS_STATUSES:
            raise ValueError("状态无效")
        with self.connect() as connection:
            connection.execute(
                "UPDATE focus_deliverables SET title=?,due_on=?,status=?,updated_at=? WHERE id=?",
                (_text(title, "交付物"), _date(due_on), status, _now(), deliverable_id),
            )
        return self.deliverable(deliverable_id)  # type: ignore[return-value]

    def set_week_focus(self, deliverable_id: str, *, selected: bool, on: date) -> None:
        row = self.deliverable(deliverable_id)
        if row is None:
            raise KeyError(deliverable_id)
        goal = self.goal(row.goal_id)
        if selected and goal.visibility == "detail_only":
            raise ValueError("仅详情可见的事项不能进入首页重点")
        week = week_start(on)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if selected:
                count = connection.execute(
                    "SELECT COUNT(*) FROM focus_deliverables d JOIN focus_goals g ON g.id=d.goal_id "
                    "WHERE g.cycle_id=? AND d.week_focus_on=? AND d.id<>?",
                    (goal.cycle_id, week, deliverable_id),
                ).fetchone()[0]
                if count >= 3:
                    raise ValueError("本周最多选择三项重点交付物")
            connection.execute(
                "UPDATE focus_deliverables SET week_focus_on=?,updated_at=? WHERE id=?",
                (week if selected else "", _now(), deliverable_id),
            )

    def actions(self, deliverable_id: str) -> tuple[FocusAction, ...]:
        return self._rows(
            "SELECT * FROM focus_actions WHERE deliverable_id=? ORDER BY due_on, title",
            FocusAction, (deliverable_id,),
        )

    def cycle_actions(self, cycle_id: str) -> tuple[FocusAction, ...]:
        return self._rows(
            "SELECT a.* FROM focus_actions a JOIN focus_deliverables d ON d.id=a.deliverable_id "
            "JOIN focus_goals g ON g.id=d.goal_id WHERE g.cycle_id=? ORDER BY a.due_on,a.title",
            FocusAction, (cycle_id,),
        )

    def action(self, action_id: str) -> FocusAction | None:
        rows = self._rows("SELECT * FROM focus_actions WHERE id=?", FocusAction, (action_id,))
        return rows[0] if rows else None

    def daily_events(self, today: date) -> tuple[DailyEvent, ...]:
        day = today.isoformat()
        return self._rows(
            "SELECT * FROM daily_events WHERE (due_on<=? AND status<>'done') "
            "OR (status='done' AND substr(updated_at,1,10)=?) ORDER BY due_on,updated_at,id",
            DailyEvent, (day, day),
        )

    def upcoming_daily_events(self, today: date) -> tuple[DailyEvent, ...]:
        return self._rows(
            "SELECT * FROM daily_events WHERE due_on>? AND status<>'done' ORDER BY due_on,title,id",
            DailyEvent, (today.isoformat(),),
        )

    def daily_event(self, event_id: str) -> DailyEvent | None:
        rows = self._rows("SELECT * FROM daily_events WHERE id=?", DailyEvent, (event_id,))
        return rows[0] if rows else None

    def planner_rows(self) -> tuple[DailyEvent, ...]:
        return self._rows("SELECT * FROM daily_events", DailyEvent)

    def planner_slots(self) -> dict[str, tuple[str, int | None]]:
        with self.connect() as connection:
            return {row["event_id"]: (row["day"], row["minute"]) for row in connection.execute("SELECT * FROM planner_slots")}

    def planner_activity(self, day: str) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(
                "SELECT * FROM planner_activity WHERE occurred_at>=? AND occurred_at<? ORDER BY id DESC",
                (day, day + "T24"),
            ).fetchall()

    def create_daily_event(
        self, title: str, today: date, deliverable_id: str = "", due_on: str = "",
        *, slot: tuple[str, int | None] | None = None,
    ) -> str:
        due_on = _date(due_on) or (slot[0] if slot else today.isoformat())
        title = _text(title, "待办")
        if deliverable_id:
            deliverable = self.deliverable(deliverable_id)
            cycle = self.current_cycle(today)
            goal = self.goal(deliverable.goal_id) if deliverable else None
            if not goal or not cycle or goal.cycle_id != cycle.id or goal.visibility != "overview":
                raise ValueError("请选择当前阶段的可见交付物")
            if {goal.status, deliverable.status} & {"done", "paused"}:
                raise ValueError("请选择尚未完成或暂缓的交付物")
        with self.connect() as connection:
            if deliverable_id:
                event = FocusAction(_id("action"), deliverable_id, title, due_on, "planned", "", _now())
                connection.execute("INSERT INTO focus_actions VALUES(?,?,?,?,?,?,?)", tuple(event.__dict__.values()))
            else:
                event = DailyEvent(_id("event"), title, due_on, "planned", _now())
                connection.execute("INSERT INTO daily_events VALUES(?,?,?,?,?)", tuple(event.__dict__.values()))
            if slot:
                connection.execute("INSERT INTO planner_slots VALUES(?,?,?)", (event.id, *slot))
            record_planner_activity(connection, event.id, "添加")
        return event.id

    def set_planner_slot(
        self, event_id: str, today: date, slot: tuple[str, int | None] | None, expected: str,
    ) -> None:
        cycle = self.current_cycle(today)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if event_id.startswith("event-"):
                event = connection.execute("SELECT status FROM daily_events WHERE id=?", (event_id,)).fetchone()
            else:
                event = connection.execute(
                    """SELECT a.status FROM focus_actions a JOIN focus_deliverables d ON d.id=a.deliverable_id
                       JOIN focus_goals g ON g.id=d.goal_id WHERE a.id=? AND g.cycle_id=? AND g.visibility='overview'
                       AND g.status NOT IN ('done','paused') AND d.status NOT IN ('done','paused')""",
                    (event_id, cycle.id if cycle else ""),
                ).fetchone()
            if event is None or event["status"] in {"done", "paused"}:
                raise ValueError("这项待办目前不能安排")
            current = connection.execute("SELECT day,minute FROM planner_slots WHERE event_id=?", (event_id,)).fetchone()
            current_slot = tuple(current) if current else None
            if expected != planner_slot_key(current_slot):
                raise ValueError("安排已变化，请刷新后重试")
            if slot == current_slot:
                return
            if slot:
                connection.execute(
                    """INSERT INTO planner_slots VALUES(?,?,?) ON CONFLICT(event_id)
                       DO UPDATE SET day=excluded.day,minute=excluded.minute""", (event_id, *slot),
                )
            else:
                connection.execute("DELETE FROM planner_slots WHERE event_id=?", (event_id,))
            record_planner_activity(connection, event_id, "安排" if slot else "取消安排")

    def update_board_event(
        self, event_id: str, status: str, today: date, *,
        title: str | None = None, due_on: str | None = None, expected_status: str = "",
    ) -> str:
        if status not in FOCUS_STATUSES:
            raise ValueError("状态无效")
        standalone = event_id.startswith("event-")
        title = _text(title, "待办") if title is not None else None
        due_on = _date(due_on, required=standalone) if due_on is not None else None
        cycle = self.current_cycle(today) if not standalone else None
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if standalone:
                table = "daily_events"
                row = connection.execute("SELECT * FROM daily_events WHERE id=?", (event_id,)).fetchone()
            else:
                table = "focus_actions"
                row = connection.execute(
                    """SELECT a.* FROM focus_actions a JOIN focus_deliverables d ON d.id=a.deliverable_id
                       JOIN focus_goals g ON g.id=d.goal_id
                       WHERE a.id=? AND g.cycle_id=? AND g.visibility='overview'""",
                    (event_id, cycle.id if cycle else ""),
                ).fetchone()
            if row is None:
                raise KeyError(event_id)
            if expected_status and row["status"] != expected_status:
                raise ValueError("这项待办的状态已变化，请检查当前状态后重试")
            if status != row["status"] or title not in (None, row["title"]) or due_on not in (None, row["due_on"]):
                connection.execute(
                    f"UPDATE {table} SET status=?, title=COALESCE(?,title), due_on=COALESCE(?,due_on), updated_at=? WHERE id=?",
                    (status, title, due_on, _now(), event_id),
                )
                action = "完成" if status == "done" and status != row["status"] else "恢复" if row["status"] == "done" and status != "done" else "更新"
                record_planner_activity(connection, event_id, action)
            return row["status"]

    def create_action(self, *, deliverable_id: str, title: str, due_on: str = "") -> FocusAction:
        if self.deliverable(deliverable_id) is None:
            raise ValueError("交付物不存在")
        row = FocusAction(_id("action"), deliverable_id, _text(title, "行动"),
                          _date(due_on), "planned", "", _now())
        with self.connect() as connection:
            connection.execute("INSERT INTO focus_actions VALUES(?,?,?,?,?,?,?)", tuple(row.__dict__.values()))
            record_planner_activity(connection, row.id, "添加")
        return row

    def update_action(self, action_id: str, *, title: str, due_on: str, status: str) -> FocusAction:
        if self.action(action_id) is None:
            raise KeyError(action_id)
        if status not in FOCUS_STATUSES:
            raise ValueError("状态无效")
        with self.connect() as connection:
            connection.execute(
                "UPDATE focus_actions SET title=?,due_on=?,status=?,updated_at=? WHERE id=?",
                (_text(title, "行动"), _date(due_on), status, _now(), action_id),
            )
        return self.action(action_id)  # type: ignore[return-value]

    def set_day_focus(self, action_id: str, *, selected: bool, on: date) -> None:
        row = self.action(action_id)
        if row is None:
            raise KeyError(action_id)
        goal = self.goal(self.deliverable(row.deliverable_id).goal_id)
        if selected and goal.visibility == "detail_only":
            raise ValueError("仅详情可见的事项不能进入首页重点")
        day = on.isoformat()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if selected:
                count = connection.execute(
                    "SELECT COUNT(*) FROM focus_actions a JOIN focus_deliverables d ON d.id=a.deliverable_id "
                    "JOIN focus_goals g ON g.id=d.goal_id WHERE g.cycle_id=? AND a.day_focus_on=? AND a.id<>?",
                    (goal.cycle_id, day, action_id),
                ).fetchone()[0]
                if count >= 3:
                    raise ValueError("今天最多选择三项重点行动")
            connection.execute(
                "UPDATE focus_actions SET day_focus_on=?,updated_at=? WHERE id=?",
                (day if selected else "", _now(), action_id),
            )

    def decisions(self, cycle_id: str) -> tuple[FocusDecision, ...]:
        return self._rows(
            "SELECT * FROM focus_decisions WHERE cycle_id=? ORDER BY due_on", FocusDecision, (cycle_id,),
        )

    def add_decision(self, *, cycle_id: str, title: str, due_on: str, question: str = "") -> FocusDecision:
        if self.cycle(cycle_id) is None:
            raise ValueError("阶段不存在")
        row = FocusDecision(_id("decision"), cycle_id, _text(title, "决策节点"),
                            _date(due_on, required=True), question.strip()[:500], "planned")
        with self.connect() as connection:
            connection.execute("INSERT INTO focus_decisions VALUES(?,?,?,?,?,?)", tuple(row.__dict__.values()))
        return row

    def update_decision_status(self, decision_id: str, *, status: str) -> FocusDecision:
        if status not in FOCUS_STATUSES:
            raise ValueError("状态无效")
        with self.connect() as connection:
            result = connection.execute(
                "UPDATE focus_decisions SET status=? WHERE id=?", (status, decision_id)
            )
            if result.rowcount == 0:
                raise KeyError(decision_id)
        rows = self._rows(
            "SELECT * FROM focus_decisions WHERE id=?", FocusDecision, (decision_id,)
        )
        return rows[0]

    def checkin(self, cycle_id: str, on: date) -> FocusCheckin | None:
        rows = self._rows(
            "SELECT * FROM focus_checkins WHERE cycle_id=? AND week_start_on=?",
            FocusCheckin, (cycle_id, week_start(on)),
        )
        return rows[0] if rows else None

    def save_checkin(self, cycle_id: str, *, on: date, completed: str, friction: str,
                     next_three: str) -> FocusCheckin:
        if self.cycle(cycle_id) is None:
            raise ValueError("阶段不存在")
        week = week_start(on)
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO focus_checkins VALUES(?,?,?,?,?,?) ON CONFLICT(cycle_id,week_start_on) "
                "DO UPDATE SET completed=excluded.completed,friction=excluded.friction,"
                "next_three=excluded.next_three,updated_at=excluded.updated_at",
                (cycle_id, week, completed.strip()[:3000], friction.strip()[:3000],
                 next_three.strip()[:3000], _now()),
            )
        return self.checkin(cycle_id, on)  # type: ignore[return-value]

    def import_plan(self, *, key: str, title: str, starts_on: str, ends_on: str,
                    goals: tuple[Mapping[str, Any], ...],
                    decisions: tuple[Mapping[str, str], ...]) -> FocusCycle:
        """Import a private plan once; a repeated key never duplicates or overwrites it."""
        existing = next((row for row in self.cycles() if row.key == key), None)
        if existing:
            return existing
        start, end = _date(starts_on, required=True), _date(ends_on, required=True)
        if end < start:
            raise ValueError("结束日期不能早于开始日期")
        cycle = FocusCycle(_id("cycle"), _text(key, "阶段标识", 100),
                           _text(title, "阶段名称"), start, end, _now())
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_row = connection.execute("SELECT * FROM focus_cycles WHERE key=?", (key,)).fetchone()
            if existing_row:
                return FocusCycle(**dict(existing_row))
            connection.execute("INSERT INTO focus_cycles VALUES(?,?,?,?,?,?)", tuple(cycle.__dict__.values()))
            for order, spec in enumerate(goals):
                area = str(spec.get("area", ""))
                priority = str(spec.get("priority", ""))
                visibility = str(spec.get("visibility", "overview"))
                module_key = str(spec.get("module_key", ""))
                if area not in FOCUS_AREAS or priority not in FOCUS_PRIORITIES:
                    raise ValueError("领域或优先级无效")
                if visibility not in FOCUS_VISIBILITIES or module_key not in FOCUS_MODULES:
                    raise ValueError("可见范围或模块无效")
                goal = FocusGoal(
                    _id("goal"), cycle.id, _text(spec.get("title"), "目标"),
                    str(spec.get("summary", "")).strip()[:500], area, priority,
                    "planned", _date(str(spec.get("target_on", ""))), visibility,
                    module_key, _external_url(str(spec.get("external_url", ""))),
                    order, _now(),
                )
                connection.execute("INSERT INTO focus_goals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", tuple(goal.__dict__.values()))
                for delivery_spec in spec.get("deliverables", ()):
                    delivery = FocusDeliverable(
                        _id("deliverable"), goal.id,
                        _text(delivery_spec.get("title"), "交付物"),
                        _date(str(delivery_spec.get("due_on", ""))),
                        "planned", "", _now(),
                    )
                    connection.execute("INSERT INTO focus_deliverables VALUES(?,?,?,?,?,?,?)", tuple(delivery.__dict__.values()))
                    for action_spec in delivery_spec.get("actions", ()):
                        action = FocusAction(
                            _id("action"), delivery.id,
                            _text(action_spec.get("title"), "行动"),
                            _date(str(action_spec.get("due_on", ""))),
                            "planned", "", _now(),
                        )
                        connection.execute("INSERT INTO focus_actions VALUES(?,?,?,?,?,?,?)", tuple(action.__dict__.values()))
            for spec in decisions:
                decision = FocusDecision(
                    _id("decision"), cycle.id,
                    _text(spec.get("title"), "决策节点"),
                    _date(str(spec.get("due_on", "")), required=True),
                    str(spec.get("question", "")).strip()[:500], "planned",
                )
                connection.execute("INSERT INTO focus_decisions VALUES(?,?,?,?,?,?)", tuple(decision.__dict__.values()))
        return cycle


def is_overdue(due_on: str, status: str, today: date) -> bool:
    return bool(due_on and due_on < today.isoformat() and status not in {"done", "paused"})


def focus_snapshot(repository: FocusRepository, today: date | None = None) -> dict[str, Any]:
    """Build a bounded UI projection; detail-only goals never enter it."""
    today = today or datetime.now(SHANGHAI).date()
    cycle = repository.current_cycle(today)
    empty = {
        "focus_cycle": cycle,
        "focus_goals": (),
        "focus_business_goals": (),
        "focus_support_goals": (),
        "focus_week": (),
        "focus_today": (),
        "focus_today_goal_ids": {},
        "focus_next_decision": None,
        "focus_next_decision_overdue": False,
        "focus_next_by_goal": {},
        "focus_visible_deliverables": (),
        "focus_visible_actions": (),
        "board_lines": (),
        "focus_today_date": today.isoformat(),
        "focus_week_start": week_start(today),
        "focus_cycle_expired": bool(cycle and cycle.ends_on < today.isoformat()),
    }
    if cycle is None:
        return empty
    goals = tuple(goal for goal in repository.goals(cycle.id) if goal.visibility == "overview")
    visible_ids = {goal.id for goal in goals}
    deliverables = tuple(
        row for row in repository.cycle_deliverables(cycle.id) if row.goal_id in visible_ids
    )
    visible_deliverable_ids = {row.id for row in deliverables}
    actions = tuple(
        row for row in repository.cycle_actions(cycle.id)
        if row.deliverable_id in visible_deliverable_ids
    )
    deliverable_goal_ids = {row.id: row.goal_id for row in deliverables}
    today_actions = tuple(
        row for row in actions if row.day_focus_on == today.isoformat()
    )
    decisions = repository.decisions(cycle.id)
    next_by_goal = {
        goal.id: next(
            (row for row in deliverables if row.goal_id == goal.id and row.status not in {"done", "paused"}),
            None,
        )
        for goal in goals
    }
    next_decision = next(
        (row for row in decisions if row.status not in {"done", "paused"}), None
    )
    counts = {goal.id: [0, 0] for goal in goals}
    for action in actions:
        count = counts[deliverable_goal_ids[action.deliverable_id]]
        count[0] += action.status == "done"
        count[1] += 1
    return {
        **empty,
        "focus_goals": goals,
        "focus_business_goals": tuple(goal for goal in goals if goal.area in {"venture", "career"}),
        "focus_support_goals": tuple(goal for goal in goals if goal.area not in {"venture", "career"}),
        "focus_week": tuple(row for row in deliverables if row.week_focus_on == week_start(today)),
        "focus_today": today_actions,
        "focus_today_goal_ids": {
            row.id: deliverable_goal_ids[row.deliverable_id] for row in today_actions
        },
        "focus_next_decision": next_decision,
        "focus_next_decision_overdue": bool(
            next_decision and is_overdue(next_decision.due_on, next_decision.status, today)
        ),
        "focus_next_by_goal": next_by_goal,
        "focus_visible_deliverables": deliverables,
        "focus_visible_actions": actions,
        "board_lines": [
            (goal, *counts[goal.id], next_by_goal[goal.id])
            for goal in sorted(goals, key=lambda goal: goal.priority)
        ],
    }


def daily_board(repository: FocusRepository, snapshot: dict, today: date) -> dict:
    day = today.isoformat()
    goals = {goal.id: goal for goal in snapshot["focus_goals"]}
    deliveries = {row.id: row for row in snapshot["focus_visible_deliverables"]}
    events = [(row, None, None) for row in repository.daily_events(today)]
    upcoming = [(row, None, None) for row in repository.upcoming_daily_events(today)]
    for action in snapshot["focus_visible_actions"]:
        delivery = deliveries[action.deliverable_id]
        goal = goals[delivery.goal_id]
        if {goal.status, delivery.status} & {"done", "paused"}:
            continue
        row = (action, goal, delivery)
        if action.day_focus_on == day or (action.status == "done" and action.updated_at[:10] == day):
            events.append(row)
        elif action.status != "done":
            if action.due_on and action.due_on <= day:
                events.append(row)
            else:
                upcoming.append(row)
    events.sort(key=lambda row: (
        row[0].status == "done", getattr(row[0], "day_focus_on", "") != day,
        row[0].due_on or day, row[0].title,
    ))
    return {
        "board_events": events,
        "board_upcoming": sorted(upcoming, key=lambda row: (row[0].due_on or "9999", row[0].title)),
        "board_deliveries": [
            (row, goals[row.goal_id]) for row in deliveries.values()
            if not ({row.status, goals[row.goal_id].status} & {"done", "paused"})
        ],
    }
