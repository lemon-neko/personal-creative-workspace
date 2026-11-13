"""Read projection for the daily calendar and task timeline."""

from calendar import Calendar, monthrange
from datetime import date, datetime, time, timedelta

from app.focus import FocusRepository, planner_slot_key
from app.workspace import SHANGHAI


def calendar_day(raw: str, today: date) -> date:
    try:
        day = date.fromisoformat(raw)
        if 2 <= day.year <= 9998:
            return day
    except ValueError:
        pass
    return today


def planner_context(repository: FocusRepository, snapshot: dict, today: date, raw_day: str) -> dict:
    selected = calendar_day(raw_day, today)
    day = selected.isoformat()
    now = datetime.now(SHANGHAI)
    slots = repository.planner_slots()
    first = selected.replace(day=1)
    last = selected.replace(day=monthrange(selected.year, selected.month)[1])
    previous = (first - timedelta(days=1)).replace(day=1)
    next_month = last + timedelta(days=1)
    month_days = tuple(Calendar().itermonthdates(selected.year, selected.month))
    counts = {value.isoformat(): 0 for value in month_days}
    goals = {goal.id: goal for goal in snapshot["focus_goals"]}
    deliveries = {row.id: row for row in snapshot["focus_visible_deliverables"]}
    events = [(event, None) for event in repository.planner_rows()]
    for action in snapshot["focus_visible_actions"]:
        delivery = deliveries[action.deliverable_id]
        goal = goals[delivery.goal_id]
        if not ({goal.status, delivery.status} & {"done", "paused"}):
            events.append((action, goal))

    by_id = {event.id: event for event, _ in events}
    all_day = []
    timed = {minute: [] for minute in range(0, 1440, 30)}
    backlog = []
    for event, goal in sorted(events, key=lambda item: (item[0].due_on or "9999", item[0].title)):
        slot = slots.get(event.id)
        assigned = slot[0] if slot else getattr(event, "day_focus_on", "") or event.due_on
        if event.status == "done" and not slot:
            assigned = event.updated_at[:10]
        if assigned in counts:
            counts[assigned] += 1
        if assigned != day and (event.status == "done" or slot):
            continue
        due = datetime.combine(date.fromisoformat(event.due_on), time(23, 59, 59), SHANGHAI) if event.due_on else None
        start = (
            datetime.combine(date.fromisoformat(slot[0]), time(slot[1] // 60, slot[1] % 60), SHANGHAI)
            if slot and slot[1] is not None else None
        )
        entry = {
            "event": event, "goal": goal, "slot": slot, "key": planner_slot_key(slot),
            "time": start.strftime("%H:%M") if start else "",
            "start_at": start.isoformat() if start and start > now else "",
            "starts_in": countdown_text(start - now) if start and start > now else "",
            "due": due.isoformat() if due else "",
            "countdown": countdown_text(due - now) if due else "",
        }
        if assigned == day:
            target = timed[slot[1]] if slot and slot[1] is not None else all_day
            target.append(entry)
        else:
            backlog.append(entry)

    activity = [
        (row["occurred_at"], row["action"], by_id[row["event_id"]].title)
        for row in repository.planner_activity(day) if row["event_id"] in by_id
    ]
    return {
        "planner_day": day, "planner_day_title": f"{selected.month}月{selected.day}日",
        "planner_weekday": "星期" + "一二三四五六日"[selected.weekday()],
        "planner_today": today.isoformat(),
        "planner_month_title": f"{selected.year}年{selected.month}月",
        "planner_month_days": [
            (value.isoformat(), value.day, value.month == selected.month, counts[value.isoformat()])
            for value in month_days
        ],
        "planner_previous": previous.isoformat() if previous.year >= 2 else "",
        "planner_next": next_month.isoformat() if next_month.year <= 9998 else "",
        "planner_all_day": all_day, "planner_backlog": backlog, "planner_activity": activity,
        "planner_hours": [(f"{minute // 60:02}:{minute % 60:02}", entries) for minute, entries in timed.items()],
    }


def countdown_text(delta: timedelta) -> str:
    overdue = delta.total_seconds() < 0
    minutes = int(abs(delta.total_seconds()) // 60)
    days, remaining = divmod(minutes, 1440)
    hours, remaining = divmod(remaining, 60)
    value = f"{days}天{hours}小时" if days else f"{hours}小时{remaining}分" if hours else f"{remaining}分钟"
    if minutes == 0:
        value = "不到 1 分钟"
    return ("逾期 " if overdue else "剩余 ") + value
