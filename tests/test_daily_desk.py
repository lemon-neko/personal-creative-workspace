from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.main import create_app
from app.privacy import CSRF_COOKIE
from app.workspace import SHANGHAI


def test_daily_desk_future_edit_schedule_and_undo(tmp_path):
    app = create_app(data_root=tmp_path, enable_scheduler=False)
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    client.get("/")
    token = client.cookies[CSRF_COOKIE]
    fragment = {"X-Workspace-Board": "1"}

    def post(path, **data):
        return client.post(path, headers=fragment, data={"csrf_token": token, **data})

    assert client.post("/today/events", headers=fragment, data={"title": "无授权事项"}).status_code == 403
    today = datetime.now(SHANGHAI).date()
    future = (today + timedelta(days=2)).isoformat()
    response = post("/today/events", title="虚构未来事项", due_on=future)
    assert response.status_code == 200
    assert "已添加到待安排" in response.text
    assert "<!doctype html>" not in response.text
    repo = app.state.focus
    event, = repo.upcoming_daily_events(today)
    assert not repo.daily_events(today)
    assert event.title in client.get("/?board=upcoming").text
    url = f"/today/events/{event.id}"
    failed = post(url + "/status?board=upcoming", edit="true", status="active", title="未保存的输入", due_on="bad")
    assert failed.status_code == 422 and 'value="未保存的输入"' in failed.text
    assert repo.upcoming_daily_events(today) == (event,)
    assert post(url + "/today?board=upcoming").status_code == 200
    assert not repo.upcoming_daily_events(today)
    assert repo.daily_events(today)[0].due_on == today.isoformat()
    assert post(url + "/status", status="active", expected_status="planned").status_code == 200
    result = post(url + "/status", status="done", expected_status="active")
    assert 'name="status" value="active"' in result.text
    assert post(url + "/status", status="blocked", expected_status="active").status_code == 422
    assert post(url + "/status", status="active", expected_status="done").status_code == 200
    assert repo.daily_events(today)[0].status == "active"


def test_schedule_keeps_phase_deadline_and_excludes_private_actions(tmp_path):
    app = create_app(data_root=tmp_path, enable_scheduler=False)
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    client.get("/")
    token = client.cookies[CSRF_COOKIE]
    today = datetime.now(SHANGHAI).date()
    future = (today + timedelta(days=2)).isoformat()
    repo = app.state.focus
    cycle = repo.import_plan(
        key="board-check", title="测试阶段", starts_on=today.isoformat(), ends_on=future,
        goals=(
            {"title": "公开计划", "area": "venture", "priority": "P0", "deliverables": ({"title": "公开交付"},)},
            {"title": "仅详情", "area": "life", "priority": "P1", "visibility": "detail_only", "deliverables": ({"title": "私有交付"},)},
        ), decisions=(),
    )
    visible, hidden = repo.goals(cycle.id)
    public_action = repo.create_action(deliverable_id=repo.deliverables(visible.id)[0].id, title="虚构对外行动", due_on=future)
    private_action = repo.create_action(deliverable_id=repo.deliverables(hidden.id)[0].id, title="私有测试行动", due_on=future)
    upcoming = client.get("/?board=upcoming")
    assert public_action.title in upcoming.text
    assert private_action.title not in upcoming.text
    assert client.post(f"/today/events/{private_action.id}/today?board=upcoming", data={"csrf_token": token}).status_code == 422
    result = client.post(f"/today/events/{public_action.id}/today?board=upcoming", data={"csrf_token": token}, follow_redirects=False)
    assert result.status_code == 303
    updated = repo.action(public_action.id)
    assert updated.day_focus_on == today.isoformat()
    assert updated.due_on == future
    assert public_action.title in client.get("/").text
