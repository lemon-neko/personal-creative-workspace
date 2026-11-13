"""Read models for the pinned Autoloop protocol. Never forward raw facts."""

import asyncio
import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

import httpx

from app.workflow_hub import EVENT_TYPE

ACTIVE = {"queued", "claimed", "unknown"}
SESSION_LINK = re.compile(r"(?:codex://threads/|claude://resume\?session=)[a-zA-Z0-9_-]{1,120}")
SECRET = re.compile(
    r"(?i)\b(?:bearer\s+[\w.+=/-]{12,}|(?:sk|ghp|github_pat|xoxb)[_-][\w.-]{12,})"
    r"|\b(?:api[_ -]?key|secret|password|token|authorization)\s*[:=]\s*[\"']?[^\s,\"']+"
)


def safe_text(value):
    if isinstance(value, list):
        return [safe_text(item) for item in value]
    return SECRET.sub("[已隐去]", value) if isinstance(value, str) else value


def pick(row, fields):
    return {key: safe_text(row.get(key)) for key in fields.split()}


def records(fact, table):
    final = {change["key"]: change["row"] for change in fact["changes"] if change["table"] == table}
    return [row for row in final.values() if row is not None]


def usage(value):
    if isinstance(value, str):
        value = json.loads(value)
    return {key: value[key] for key in ("input", "output", "cached", "cost") if key in (value or {})} or None


def rule_fields(rule):
    view = pick(rule, "name to group parallel maxActive tell skill")
    cwd = rule.get("cwd")
    if cwd:
        home = str(Path.home())
        if "/working/plugins/" in cwd:
            view["cwd"] = "$PCW_PLUGINS/" + cwd.split("/working/plugins/", 1)[1]
        elif cwd.startswith(home + "/"):
            view["cwd"] = "~" + cwd[len(home):]
        elif Path(cwd).is_absolute():
            view["cwd"] = "$LOCAL_PATH"
        else:
            view["cwd"] = cwd
    for field in ("when", "emits"):
        if isinstance(rule.get(field), dict):
            view[field] = pick(rule[field], "source types cron")
        elif isinstance(rule.get(field), str):
            view[field] = rule[field]
    return view


def trace(run_id, facts):
    facts = sorted(facts, key=lambda fact: fact["seq"])
    event_ids = {
        row["event_id"] for fact in facts for row in records(fact, "run_events") if row["run_id"] == run_id
    }
    rows = [row for fact in facts for row in records(fact, "runs") if row["id"] == run_id]
    final = rows[-1] if rows else {}
    group, lane = final.get("grp"), final.get("lane")
    card_rows = {
        row["id"]: row for fact in facts for row in records(fact, "cards")
        if row.get("run_id") == run_id or row.get("answer_event") in event_ids
    }
    answer_events = {row["answer_event"]: cid for cid, row in card_rows.items() if row.get("answer_event")}
    links = {
        (answer_events[row["event_id"]], row["run_id"])
        for fact in facts for row in records(fact, "run_events") if row["event_id"] in answer_events
    }
    configurations = {
        fact["seq"]: row["value"] for fact in facts for row in records(fact, "config")
        if fact["type"] == "rules" and isinstance(row.get("value"), dict) and "rules" in row["value"]
    }
    timeline, frames, cards, seen_cards, timer_ids = [], [], {}, set(), set()
    current_version = started = worker = last_claim = None
    matter_added = False
    for fact in facts:
        first = len(timeline)
        run_row = next((row for row in records(fact, "runs") if row["id"] == run_id), None)

        def add(kind, **fields):
            timeline.append({
                "kind": kind, "seq": fact["seq"], "at": fact["at"], "factType": fact["type"],
                **{key: safe_text(value) for key, value in fields.items()},
            })

        for event in records(fact, "events"):
            if event["id"] in event_ids:
                add("event", event=event["id"], **pick(event, "source type subject summary received_at"),
                    card=answer_events.get(event["id"]))
        for row in records(fact, "runs"):
            if row["id"] != run_id:
                continue
            version = row.get("rules_version")
            config = configurations.get(version, {})
            rule = next((rule for rule in config.get("rules", []) if rule["name"] == row.get("rule")), None)
            worker = config.get("agents", {}).get(row.get("agent"), {}).get("worker")
            if version != current_version:
                add("rule", rule=row.get("rule"), version=version, config=rule_fields(rule) if rule else None)
                current_version = version
            if not matter_added:
                add("matter", group=row.get("grp"), lane=row.get("lane"))
                matter_added = True
                if row.get("state") == "queued":
                    add("queue", state="queued", createdAt=row.get("created_at"))
            claim_identity = (row.get("claim"), row.get("claimed_at"))
            if fact["type"] == "claimNext" and claim_identity != last_claim:
                add("claim", worker=worker, agent=row.get("agent"))
                started = None
            last_claim = claim_identity
            if fact["type"] == "started":
                started = fact["at"]
                add("start", agent=row.get("agent"), session=row.get("session"), resume=row.get("resume"),
                    link=session_link(row.get("link")))
            if fact["type"] == "finish":
                add("receipt", outcome="failed" if row.get("state") == "queued" else row.get("state"),
                    **pick(row, "summary error attempts not_before"), usage=usage(row.get("usage")))
                for event in records(fact, "events"):
                    if event["id"] in json.loads(row.get("emitted") or "[]"):
                        add("emit", event=event["id"], **pick(event, "source type subject summary"))
                for change in fact["changes"]:
                    if change["table"] == "timers" and change["row"] is None and change["key"] in timer_ids:
                        timer_ids.remove(change["key"])
                        add("later", timer=change["key"], cancelled=True)
                for timer in records(fact, "timers"):
                    if (timer.get("rule"), timer.get("lane")) == (row.get("rule"), row.get("lane")):
                        if timer.get("id") is not None:
                            timer_ids.add(str(timer["id"]))
                        add("later", timer=timer.get("id"), **pick(timer, "key about"), due=timer.get("at"))
            if fact["type"] == "cancel":
                add("stop", state=row.get("state"))
            if fact["type"] == "tick" and row.get("state") == "unknown":
                add("unknown", error=row.get("error"))
        for card in records(fact, "cards"):
            cid = card["id"]
            if cid not in card_rows:
                continue
            if cid not in seen_cards:
                seen_cards.add(cid)
                add("card", card=cid, originRun=card.get("run_id"), cardKind=card["kind"],
                    **pick(card, "title text state fyi"))
            if card.get("decided_at") and cards.get(cid, {}).get("decided_at") != card["decided_at"]:
                options = json.loads(card.get("options") or "[]")
                choice = card.get("choice")
                add("answer", card=cid, originRun=card.get("run_id"),
                    selected=options[choice] if choice in range(len(options)) else None,
                    **pick(card, "choice answer by decided_at"))
            if card.get("closed_at") and cards.get(cid, {}).get("closed_at") != card["closed_at"]:
                add("card_closed", card=cid, originRun=card.get("run_id"), **pick(card, "state result"))
            cards[cid] = pick(card, "id kind title text state fyi run_id answer_event choice answer by result rule")
            cards[cid].update(
                options=safe_text(json.loads(card.get("options") or "[]")), recommend=card.get("recommend"),
                createdAt=card.get("created_at"), decidedAt=card.get("decided_at"), closedAt=card.get("closed_at"),
            )
            cards[cid]["decided_at"] = card.get("decided_at")
            cards[cid]["closed_at"] = card.get("closed_at")
        for row in records(fact, "run_events"):
            cid = answer_events.get(row["event_id"])
            if cid is not None:
                add("followup", card=cid, originRun=card_rows[cid].get("run_id"), run=row["run_id"])
        if len(timeline) > first or run_row or fact["seq"] in configurations:
            frames.append({
                "seq": fact["seq"], "at": fact["at"], "type": fact["type"],
                "run": pick(run_row, "state attempts claimed_at finished_at not_before") if run_row else None,
                "steps": timeline[first:],
            })
    for cid, card in cards.items():
        card["following"] = sorted(following for card_id, following in links if card_id == cid)
    return {
        "id": run_id, "group": group, "lane": lane, "worker": worker, "started": started,
        "ruleVersion": current_version, "rule": final.get("rule"), "agent": final.get("agent"),
        "state": final.get("state"), "attempts": final.get("attempts"), "session": final.get("session"),
        "resume": final.get("resume"),
        "stopping": bool(final.get("cancel_at")),
        "claimedAt": final.get("claimed_at"), "finishedAt": final.get("finished_at"),
        "link": session_link(final.get("link")), "usage": usage(final.get("usage")),
        "cards": list(cards.values()), "timeline": timeline, "frames": frames,
        "missing": [
            label for label, missing in (
                ("首次入队", not any(step["kind"] == "queue" for step in timeline)),
                ("关联事件", not any(step["kind"] == "event" for step in timeline)),
                ("规则版本内容", current_version is not None and current_version not in configurations),
                ("开始事实", final.get("session") and not any(step["kind"] == "start" for step in timeline)),
                ("终态回执", final.get("state") in {"done", "nothing"} and not any(
                    step["kind"] == "receipt" for step in timeline
                )),
            ) if missing
        ],
    }


def session_link(value):
    return value if isinstance(value, str) and SESSION_LINK.fullmatch(value) else None


def _same_workflow_day(raw, cutoff):
    zone = ZoneInfo(raw["timezone"])
    return datetime.fromisoformat(raw["now"]).astimezone(zone).date() == (
        datetime.fromisoformat(cutoff["time"]).astimezone(zone).date()
    )


async def snapshot(workflow, before=None):
    raw = await workflow.autoloop.request("/v1/state", params={"before": before} if before else None)
    cutoff = workflow.store.archive()
    raw["runs"] = [row for row in raw["runs"] if row["id"] > cutoff.get("run", 0)]
    for kind in ("cards", "recentCards"):
        raw[kind] = [row for row in raw[kind] if row["id"] > cutoff.get("card", 0)]
    if raw["nextBefore"] and raw["nextBefore"] <= cutoff.get("run", 0) + 1:
        raw.update(nextBefore=None, hasMore=False)
    for key, old in cutoff.get("totals", {}).items():
        if key != "doneToday" or _same_workflow_day(raw, cutoff):
            raw["totals"][key] = max(0, raw["totals"][key] - old)
    for source in raw["sources"]:
        source["events"] = max(0, source["events"] - cutoff.get("sources", {}).get(source["id"], 0))
    items = workflow.store.active_items()
    turns = workflow.store.turn_links()
    local_by_run = {turn["run"]: turn for turn in turns if turn["run"] is not None}
    local_by_turn = {turn["id"]: turn["item_id"] for turn in turns}
    item_by_id = {item["id"]: item for item in items}
    agents = {agent["id"]: agent for agent in raw["agents"]}
    limit = asyncio.Semaphore(8)
    cache = workflow.control_traces

    async def enrich(run):
        run_id = run["id"]
        signature = json.dumps(run, sort_keys=True)
        cached = cache.get(run_id)
        if cached and cached[0] == signature:
            details = cached[1]
        else:
            try:
                async with limit:
                    projected = trace(run_id, await workflow.autoloop.request(f"/v1/runs/{run_id}/why"))
                    details = pick(projected, "group lane worker started cards")
                    details["activity"] = [
                        pick(step, "seq at kind event source type subject received_at rule card cardKind outcome state due timer run summary originRun")
                        for step in projected["timeline"][-60:]
                    ]
            except httpx.HTTPError:
                details = {}
            else:
                cache[run_id] = (signature, details)
                cache.move_to_end(run_id)
                if len(cache) > 240:
                    cache.popitem(last=False)
        local = local_by_run.get(run_id, {})
        # The subject from the approved event is available before the worker links its local turn.
        item_id = local.get("item_id") or next((
            event.get("subject") for event in run["events"]
            if event["source"] == "workbench" and event["type"] == EVENT_TYPE
            and event.get("subject") in item_by_id
        ), None)
        group, lane = details.get("group"), details.get("lane")
        matter = ["local", item_id] if item_id else ["lane", group, lane] if group is not None else ["run", run_id]
        label = item_by_id.get(item_id, {}).get("title") or next((
            event["summary"] for event in reversed(run["events"])
            if event.get("summary") and event["type"] not in ("card.answered", "timer.due", "run.manual")
        ), None)
        title = label or lane or run["rule"]
        safe = pick(run, "id rule agent state attempts createdAt claimedAt finishedAt notBefore summary error stopping manual session")
        safe.update(
            matter=matter, group=group, lane=lane, item=item_id, title=title, label=label, worker=details.get("worker"),
            started=details.get("started"), previous=local.get("previous_run"), usage=usage(run["usage"]),
            sources=list(dict.fromkeys(event["source"] for event in run["events"])),
            cards=[card["id"] for card in details.get("cards", [])],
            observed=list(dict.fromkeys(step["kind"] for step in details.get("activity", []))),
        )
        return safe, details

    enriched = await asyncio.gather(*(enrich(run) for run in raw["runs"]))
    runs = [run for run, _ in enriched]
    metadata = {}
    for _, details in enriched:
        for card in details.get("cards", []):
            entry = metadata.setdefault(card["id"], {**card, "following": []})
            entry["following"] = sorted(set(entry["following"]) | set(card["following"]))

    def card_view(card):
        meta = metadata.get(card["id"], {})
        item = local_by_turn.get(card.get("about"))
        return pick(card, "id kind state title text options recommend choice answer by result rule lane createdAt decidedAt closedAt") | {
            "item": item, "run": meta.get("run_id"), "following": meta.get("following", []),
            "fyi": bool(meta["fyi"]) if "fyi" in meta else None,
            "answer": safe_text(workflow.store.resolve_answer(card["id"], card["answer"])),
        }

    lines = []
    try:
        config = json.loads((workflow.store.root / "autoloop-data" / "rules.json").read_text())
        on_disk = {rule["name"]: rule_fields(rule) for rule in config["rules"]}
    except (OSError, ValueError, TypeError, KeyError):
        on_disk = {}
    for line in raw["lines"]:
        lines.append(pick(line, "id name group agent source types every next totals skippedAt") | {
            "paused": bool(line["paused"]), "worker": agents.get(line["agent"], {}).get("worker"),
            "file": on_disk.get(line["name"]),
        })
    activity = sorted(
        [step | {"runId": step["originRun"] or run["id"]} for run, details in enriched for step in details.get("activity", [])],
        key=lambda step: step["seq"], reverse=True,
    )
    return pick(raw, "seq now timezone totals nextBefore hasMore") | {
        "sources": [pick(source, "id name events") for source in raw["sources"]],
        "agents": [pick(agent, "id name use worker online seenAt totals") for agent in raw["agents"]],
        "channels": [pick(channel, "id name online seenAt") for channel in raw["channels"]],
        "lines": lines, "runs": runs, "items": items,
        "cards": [card_view(card) for card in raw["cards"] + raw["recentCards"]],
        "timers": [pick(timer, "rule lane key about at") for timer in raw["timers"]],
        "unrouted": [pick(event, "id source type subject summary received_at") for event in raw["unrouted"]],
        "activity": activity[:100],
    }


def invalidate(workflow, fact):
    changed = set()
    for row in records(fact, "runs"):
        if fact["type"] != "heartbeat":
            changed.add(row["id"])
    for row in records(fact, "run_events"):
        changed.add(row["run_id"])
    for row in records(fact, "cards"):
        if row.get("run_id") is not None:
            changed.add(row["run_id"])
    for run in changed:
        workflow.control_traces.pop(run, None)
    return {"runs": sorted(changed), "tables": sorted({change["table"] for change in fact["changes"]} - {"keys"})}


TIMELINE_LABELS = {
    "event": "事件接入", "rule": "规则匹配", "matter": "事项归并", "queue": "进入队列",
    "claim": "Worker 领取", "start": "Agent 开始执行", "receipt": "提交回执",
    "emit": "Events · 发出事件", "later": "Later · 定时复查", "card": "生成卡片",
    "answer": "人工回答", "card_closed": "卡片处理结果", "followup": "关联续跑",
    "stop": "停止请求", "unknown": "状态不确定",
}


def run_details(store, run_id, facts):
    details = trace(run_id, facts)
    for step in details["timeline"]:
        if step["kind"] == "answer":
            step["answer"] = safe_text(store.resolve_answer(step["card"], step["answer"]))
    for card in details["cards"]:
        card["answer"] = safe_text(store.resolve_answer(card["id"], card["answer"]))
    turns = store.turn_links()
    current = next((turn for turn in turns if turn["run"] == run_id), {})
    details["item"] = current.get("item_id")
    details["previous"] = current.get("previous_run")
    details["following"] = [turn["run"] for turn in turns if turn["previous_run"] == run_id and turn["run"] is not None]
    details["nativeFollowing"] = sorted({
        following for card in details["cards"] if card.get("run_id") == run_id for following in card["following"]
    } - {run_id})
    return details


def execution_details(store, details):
    turn = store.linked_turn(details["id"])
    telemetry, output = [], None
    if turn:
        telemetry = store.telemetry(turn["id"])
        if turn["state"] in ("draft", "accepted", "decision"):
            try:
                candidate = store.payload(turn["id"])
                if "draft" in candidate:
                    output = safe_text(candidate["draft"])
                elif "question" in candidate:
                    output = "\n".join(safe_text(line) for line in [candidate["question"], *candidate["options"]])
            except (OSError, ValueError, KeyError, TypeError):
                pass
    return {
        "events": telemetry, "output": output, "localState": turn["state"] if turn else None,
    }


def matter_details(store, view, *, item=None, seed=None):
    """Join only on the persisted workbench ID or the native group and lane."""
    runs = view.get("runs", [])
    turns = store.turns(item["id"]) if item else []
    if item:
        linked = {turn["run"]: turn for turn in turns if turn["run"] is not None}
        found = {run["id"]: run for run in runs if run["id"] in linked}
        selected = [
            found.get(run_id, {"id": run_id, "createdAt": datetime.fromisoformat(
                turn["created_at"]
            ).replace(tzinfo=timezone.utc).isoformat()}) | {"localState": turn["state"]}
            for run_id, turn in linked.items()
        ]
    else:
        identity = ["lane", seed["group"], seed["lane"]] if seed["group"] is not None else ["run", seed["id"]]
        selected = [run for run in runs if run["matter"] == identity]
    if seed and not any(run["id"] == seed["id"] for run in selected):
        selected.append(pick(seed, "id state rule agent group lane worker started claimedAt finishedAt"))
    ids = {run["id"] for run in selected}
    native_cards = {card["id"]: card for card in (seed or {}).get("cards", []) if card.get("run_id") in ids}
    for card in view.get("cards", []):
        if card["run"] in ids or (item and card["item"] == item["id"]):
            native_cards[card["id"]] = card
    group_lane = {(run.get("rule"), run.get("lane")) for run in selected if run.get("group") is not None}
    return {
        "item": item["id"] if item else None, "title": safe_text(item["title"]) if item else (
            next((run["title"] for run in selected if run.get("title")), None) or seed["lane"] or seed["rule"]
        ),
        "identity": [item["id"]] if item else [seed["group"], seed["lane"]],
        "localState": turns[0]["state"] if turns else None,
        "runs": sorted(selected, key=lambda run: run["id"], reverse=True),
        "cards": list(native_cards.values()),
        "timers": [timer for timer in view.get("timers", []) if (timer["rule"], timer["lane"]) in group_lane],
    }


def cancellation_links(run_id, facts):
    event_ids = {
        row["event_id"] for fact in facts for row in records(fact, "run_events") if row["run_id"] == run_id
    }
    approved_events = {
        (event["key"], event["subject"])
        for fact in facts for event in records(fact, "events")
        if event["id"] in event_ids and event["type"] == EVENT_TYPE and event["source"] == "workbench"
    }
    cards = {
        card["id"] for fact in facts for card in records(fact, "cards")
        if card.get("answer_event") in event_ids
    }
    return approved_events, cards


async def stream_events(workflow, after):
    try:
        async with workflow.autoloop.facts(after) as facts:
            yield 'retry: 2500\nevent: connected\ndata: {}\n\n'
            async for fact in facts:
                safe = json.dumps(invalidate(workflow, fact))
                yield f"id: {fact['seq']}\nevent: fact\ndata: {safe}\n\n"
    except (RuntimeError, httpx.HTTPError, ValueError, KeyError):
        pass
    yield 'retry: 2500\nevent: disconnected\ndata: {}\n\n'
