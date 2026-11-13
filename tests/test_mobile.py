from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.content import load_items, semantic_revision
from app.main import create_app
from app.mobile import MobileCaptureService, MobileStore, OfflineCapture
from app.mobile_daily import daily_now
from app.mobile_launcher import _funnel_enabled, validate_mobile_environment
from app.mobile_main import _is_same_tailnet_origin, create_mobile_app
from app.plugins import WORKBENCH_ORIGIN
from app.workspace import create_item, items_directory, set_item_status, update_item


TAILNET_HOST = "yubai-mac.example.ts.net"
TAILNET_HEADERS = {
    "x-forwarded-proto": "https",
    "x-forwarded-for": "100.64.0.42",
    "origin": f"https://{TAILNET_HOST}",
}


def configured_store(tmp_path: Path) -> MobileStore:
    store = MobileStore(tmp_path)
    store.save_config(enabled=True, tailnet_host=TAILNET_HOST)
    return store


def mobile_client(tmp_path: Path) -> tuple[TestClient, MobileStore]:
    store = configured_store(tmp_path)
    app = create_mobile_app(data_root=tmp_path, content_root=tmp_path / "content")
    client = TestClient(
        app,
        base_url=f"https://{TAILNET_HOST}",
        client=("127.0.0.1", 32100),
        headers=TAILNET_HEADERS,
    )
    return client, store


def pair(client: TestClient, store: MobileStore) -> str:
    home = client.get("/")
    pair_csrf = client.cookies.get("pcw_mobile_pair_csrf")
    assert home.status_code == 200 and pair_csrf
    code, _ = store.create_pairing_code()
    response = client.post(
        "/pair",
        data={
            "code": code,
            "device_name": "Pixel 10",
            "csrf_token": pair_csrf,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    session = client.get("/api/session")
    assert session.status_code == 200
    return session.json()["csrf_token"]


def test_mobile_store_pairing_is_single_use_and_revocable(tmp_path: Path) -> None:
    store = configured_store(tmp_path)
    code, _ = store.create_pairing_code()
    device, token = store.pair(code, "Pixel")

    assert store.authenticate(token).device_id == device.id
    with pytest.raises(ValueError, match="无效或已过期"):
        store.pair(code, "另一台手机")
    store.revoke_device(device.id)
    assert store.authenticate(token) is None
    assert oct((tmp_path / "mobile.db").stat().st_mode & 0o777) == "0o600"
    assert oct((tmp_path / "mobile.secret").stat().st_mode & 0o777) == "0o600"


def test_mobile_gateway_requires_tailnet_proxy_and_configured_host(
    tmp_path: Path,
) -> None:
    configured_store(tmp_path)
    app = create_mobile_app(data_root=tmp_path, enforce_security=True)

    direct = TestClient(
        app,
        base_url=f"https://{TAILNET_HOST}",
        client=("100.64.0.42", 1234),
        headers=TAILNET_HEADERS,
    )
    wrong_host = TestClient(
        app,
        base_url="https://evil.example.ts.net",
        client=("127.0.0.1", 1234),
        headers=TAILNET_HEADERS,
    )
    public_forwarded = TestClient(
        app,
        base_url=f"https://{TAILNET_HOST}",
        client=("127.0.0.1", 1234),
        headers={**TAILNET_HEADERS, "x-forwarded-for": "8.8.8.8"},
    )

    assert direct.get("/").status_code == 403
    assert wrong_host.get("/").status_code == 403
    assert public_forwarded.get("/").status_code == 403


def test_mobile_gateway_accepts_valid_tailscale_forwarded_host(tmp_path: Path) -> None:
    client, _ = mobile_client(tmp_path)

    response = client.get(
        "/",
        headers={**TAILNET_HEADERS, "x-forwarded-host": f"{TAILNET_HOST}:443"},
    )

    assert response.status_code == 200


def test_mobile_gateway_rejects_spoofed_forwarded_host(tmp_path: Path) -> None:
    client, _ = mobile_client(tmp_path)

    response = client.get(
        "/",
        headers={**TAILNET_HEADERS, "x-forwarded-host": "attacker.example:443"},
    )

    assert response.status_code == 403


def test_mobile_pwa_assets_are_local_and_do_not_cache_private_api(
    tmp_path: Path,
) -> None:
    client, _ = mobile_client(tmp_path)

    assert client.get("/").status_code == 200
    manifest = client.get("/manifest.webmanifest")
    worker = client.get("/service-worker.js")
    assert manifest.json()["name"] == "羽白工作台"
    assert manifest.json()["short_name"] == "羽白工作台"
    assert manifest.json()["display"] == "standalone"
    assert "indexedDB" in client.get("/mobile-assets/mobile.js").text
    assert 'url.pathname.startsWith("/api/")' in worker.text
    assert "yubai-mobile-shell-v7" in worker.text
    assert 'styles/base.css?v=7' in worker.text
    assert 'mobile.js?v=7' in worker.text
    assert "CACHE_KNOWLEDGE_PATHS" not in worker.text
    assert 'key.startsWith("yubai-mobile-")' in worker.text
    assert "self.skipWaiting()" in worker.text
    assert "self.clients.claim()" in worker.text
    assert 'caches.match("/offline")' in worker.text
    assert "syncWorkspace()" in worker.text
    assert "ideaEdits" in worker.text
    assert 'isIdeaPath(url.pathname)' in worker.text
    assert "registration.sync.register" in client.get("/mobile-assets/mobile.js").text
    assert "capture-form" in client.get("/offline").text


def test_mobile_board_accepts_only_current_minimal_desktop_snapshot(tmp_path: Path) -> None:
    mobile, store = mobile_client(tmp_path)
    app = create_app(data_root=tmp_path, enable_scheduler=False, enforce_security=True)
    desktop = TestClient(app, base_url=WORKBENCH_ORIGIN)
    desktop.get("/tasks")
    headers = {"X-CSRF-Token": desktop.cookies["pcw_csrf"], "Origin": WORKBENCH_ORIGIN}
    url = "/workflow/daily-snapshot"
    now = daily_now()
    yesterday = (now.date() - timedelta(days=1)).isoformat()
    payload = {
        "day": now.date().isoformat(),
        "today": [{"title": "虚构排期", "when": "10:30"}],
        "overdue": [{"title": "虚构逾期", "when": yesterday}],
        "unplanned": [{"title": "虚构待安排"}],
        "done": [{"title": "虚构已完成"}],
    }
    snapshot = tmp_path / "working" / "mobile-daily.json"

    assert desktop.post(url, json=payload, headers=headers).status_code == 404
    app.state.plugins_enabled = True
    assert desktop.post(url, json=payload, headers={"Origin": WORKBENCH_ORIGIN}).status_code == 403
    assert desktop.post(url, json=payload, headers=headers | {"Origin": "http://localhost:8767"}).status_code == 403
    assert desktop.post(url, json=payload | {"day": yesterday}, headers=headers).status_code == 409
    assert desktop.post(url, json=payload | {
        "today": [{"title": "虚构排期", "notes": "不应同步"}],
    }, headers=headers).status_code == 422
    store.save_config(enabled=False, tailnet_host=TAILNET_HOST)
    assert desktop.post(url, json=payload, headers=headers).status_code == 404
    assert not snapshot.exists()
    store.save_config(enabled=True, tailnet_host=TAILNET_HOST)

    assert desktop.post(url, json=payload, headers=headers).status_code == 200
    assert snapshot.stat().st_mode & 0o777 == 0o600
    assert "虚构排期" not in mobile.get("/").text
    assert mobile.get("/capture", follow_redirects=False).status_code == 303
    pair(mobile, store)
    board = mobile.get("/")
    assert board.headers["cache-control"] == "no-store"
    for group in ("今日安排", "逾期待办", "待安排", "今日完成"):
        assert group in board.text
    for group in ("today", "overdue", "unplanned", "done"):
        assert payload[group][0]["title"] in board.text
    assert "10:30" in board.text and "桌面同步于" in board.text

    snapshot.write_text(snapshot.read_text().replace(payload["day"], yesterday))
    empty = mobile.get("/")
    assert "还没有今天的快照" in empty.text
    assert "虚构排期" not in empty.text


def test_mobile_capture_has_no_knowledge_routes(tmp_path: Path) -> None:
    client, store = mobile_client(tmp_path)
    csrf = pair(client, store)
    capture = client.get("/capture")
    assert "capture-form" in capture.text
    assert 'href="/ideas"' in capture.text
    for path in ("/knowledge", "/knowledge/maps/example", "/knowledge/cards/example"):
        assert client.get(path).status_code == 404
    assert client.post(
        "/api/ideas/example/knowledge/cards", json={}, headers={"X-CSRF-Token": csrf},
    ).status_code == 404
    assert "topics" not in client.get("/api/ideas/snapshot").json()


def test_capture_requires_pairing_csrf_and_origin(tmp_path: Path) -> None:
    client, store = mobile_client(tmp_path)
    data = {"idempotency_key": "capture-1", "body": "手机闪念"}

    assert client.post("/api/captures", data=data).status_code == 401
    csrf = pair(client, store)
    assert client.post("/api/captures", data=data).status_code == 403
    assert (
        client.post(
            "/api/captures",
            data=data,
            headers={"x-csrf-token": csrf, "origin": "https://evil.example"},
        ).status_code
        == 403
    )


def test_mobile_origin_accepts_explicit_default_https_port_only() -> None:
    assert _is_same_tailnet_origin(f"https://{TAILNET_HOST}", TAILNET_HOST)
    assert _is_same_tailnet_origin(f"https://{TAILNET_HOST}:443", TAILNET_HOST)
    assert not _is_same_tailnet_origin(f"http://{TAILNET_HOST}", TAILNET_HOST)
    assert not _is_same_tailnet_origin(f"https://{TAILNET_HOST}:8443", TAILNET_HOST)
    assert not _is_same_tailnet_origin("https://evil.example", TAILNET_HOST)


def test_mobile_pair_accepts_same_origin_referer_when_origin_is_omitted(
    tmp_path: Path,
) -> None:
    client, store = mobile_client(tmp_path)
    client.get("/")
    pair_csrf = client.cookies.get("pcw_mobile_pair_csrf")
    code, _ = store.create_pairing_code()

    response = client.post(
        "/pair",
        data={"code": code, "device_name": "Android", "csrf_token": pair_csrf},
        headers={
            "origin": "",
            "referer": f"https://{TAILNET_HOST}/",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303


def test_mobile_pair_accepts_opaque_origin_with_double_submit_token(
    tmp_path: Path,
) -> None:
    client, store = mobile_client(tmp_path)
    client.get("/")
    pair_csrf = client.cookies.get("pcw_mobile_pair_csrf")
    code, _ = store.create_pairing_code()

    response = client.post(
        "/pair",
        data={"code": code, "device_name": "Android", "csrf_token": pair_csrf},
        headers={"origin": "null", "referer": ""},
        follow_redirects=False,
    )

    assert response.status_code == 303


def test_mobile_pair_rejects_opaque_origin_without_double_submit_token(
    tmp_path: Path,
) -> None:
    client, store = mobile_client(tmp_path)
    code, _ = store.create_pairing_code()

    response = client.post(
        "/pair",
        data={"code": code, "device_name": "Android", "csrf_token": "forged"},
        headers={"origin": "null", "referer": ""},
        follow_redirects=False,
    )

    assert response.status_code == 403


def test_capture_is_idempotent_and_writes_private_markdown_and_image(
    tmp_path: Path,
) -> None:
    client, store = mobile_client(tmp_path)
    csrf = pair(client, store)
    payload = {
        "idempotency_key": "offline-idea-001",
        "body": "公交车上突然想到，等待也许是一种缓冲区。",
        "title": "等待与缓冲区",
        "tags": "生活,观察",
        "category": "通勤",
        "created_at": "2026-08-13T00:00:00.725Z",
    }
    png = b"\x89PNG\r\n\x1a\n" + b"private-image"
    first = client.post(
        "/api/captures",
        data=payload,
        files=[("images", ("photo.png", png, "image/png"))],
        headers={"x-csrf-token": csrf},
    )
    second = client.post("/api/captures", data=payload, headers={"x-csrf-token": csrf})
    collection = load_items(items_directory(tmp_path / "content"))

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["content_id"] == second.json()["content_id"]
    assert second.json()["created"] is False
    assert len(collection.items) == 1
    item = collection.items[0]
    assert item.title == "等待与缓冲区"
    assert "/assets/mobile-" in item.body
    assert oct(item.source.stat().st_mode & 0o777) == "0o600"
    images = tuple((tmp_path / "content" / "assets").glob("mobile-*.png"))
    assert len(images) == 1
    assert oct(images[0].stat().st_mode & 0o777) == "0o600"


def test_mobile_idea_snapshot_only_contains_unarchived_thoughts(
    tmp_path: Path,
) -> None:
    content_root = tmp_path / "content"
    visible = create_item(content_root, body="可以在手机继续修改的随想。")
    archived = create_item(content_root, body="已经归档的随想。")
    set_item_status(content_root, archived.id, "archived")
    create_item(content_root, body="文章正文。", kind="article")
    create_item(content_root, body="周回顾正文。", kind="weekly-review")
    client, store = mobile_client(tmp_path)
    pair(client, store)

    response = client.get("/api/ideas/snapshot")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [visible.id]
    assert response.json()["items"][0]["revision"] == semantic_revision(visible)
    assert client.get("/ideas").status_code == 200
    assert "我的随想" in client.get("/ideas").text
    assert client.get(f"/ideas/{visible.id}").status_code == 200


def test_mobile_idea_edit_is_idempotent_and_detects_revision_conflict(
    tmp_path: Path,
) -> None:
    content_root = tmp_path / "content"
    item = create_item(content_root, body="最初版本。", title="一条想法")
    client, store = mobile_client(tmp_path)
    csrf = pair(client, store)
    payload = {
        "operation_key": "edit-operation-001",
        "expected_revision": semantic_revision(item),
        "body": "手机离线编辑后的版本。",
        "title": "手机编辑",
        "tags": "生活,观察",
        "category": "通勤",
    }
    png = b"\x89PNG\r\n\x1a\n" + b"mobile-edit"

    first = client.post(
        f"/api/ideas/{item.id}",
        data=payload,
        files=[("images", ("new.png", png, "image/png"))],
        headers={"x-csrf-token": csrf},
    )
    replay = client.post(
        f"/api/ideas/{item.id}",
        data=payload,
        headers={"x-csrf-token": csrf},
    )
    saved = load_items(items_directory(content_root)).get(item.id)

    assert first.status_code == 200 and first.json()["applied"] is True
    assert replay.status_code == 200 and replay.json()["applied"] is False
    assert saved.title == "手机编辑"
    assert "手机离线编辑后的版本" in saved.body
    assert saved.body.count("/assets/mobile-edit-") == 1

    stale_revision = first.json()["revision"]
    update_item(content_root, item.id, body="Obsidian 后来又更新了正文。")
    conflict = client.post(
        f"/api/ideas/{item.id}",
        data={
            **payload,
            "operation_key": "edit-operation-002",
            "expected_revision": stale_revision,
            "body": "另一个手机版本。",
        },
        headers={"x-csrf-token": csrf},
    )

    assert conflict.status_code == 409
    assert conflict.json()["current"]["body"] == "Obsidian 后来又更新了正文。"
    assert load_items(items_directory(content_root)).get(item.id).body == (
        "Obsidian 后来又更新了正文。"
    )

    merged = client.post(
        f"/api/ideas/{item.id}/resolve",
        data={
            **payload,
            "operation_key": "edit-operation-003",
            "expected_revision": conflict.json()["current"]["revision"],
            "body": "人工对比后保存的合并版本。",
        },
        headers={"x-csrf-token": csrf},
    )
    assert merged.status_code == 200 and merged.json()["applied"] is True
    assert load_items(items_directory(content_root)).get(item.id).body == (
        "人工对比后保存的合并版本。"
    )


@pytest.mark.parametrize(
    "image",
    [b"<svg><script>alert(1)</script></svg>", b"GIF89a", b"not-an-image"],
)
def test_capture_rejects_dangerous_or_unsupported_images(
    tmp_path: Path, image: bytes
) -> None:
    store = configured_store(tmp_path)
    service = MobileCaptureService(tmp_path, tmp_path / "content", store)

    with pytest.raises(ValueError, match="图片格式无效"):
        service.create_capture(OfflineCapture("image-test", "正文"), [image])
    assert not tuple((tmp_path / "content" / "assets").glob("*"))


def test_desktop_mobile_settings_manage_config_and_devices(tmp_path: Path) -> None:
    desktop = TestClient(create_app(content_root=tmp_path, enable_scheduler=False))

    page = desktop.get("/settings/mobile")
    saved = desktop.post(
        "/settings/mobile/config",
        data={"enabled": "on", "tailnet_host": TAILNET_HOST},
        follow_redirects=True,
    )
    pairing = desktop.post("/settings/mobile/pairing-code")

    assert page.status_code == 200 and "Android 羽白工作台" in page.text
    assert "手机离线边界" in page.text and "未归档随想快照" in page.text
    assert saved.status_code == 200 and "手机同步配置已保存" in saved.text
    assert pairing.status_code == 200 and "十分钟内有效" in pairing.text


def test_launcher_rejects_funnel_and_missing_serve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = configured_store(tmp_path)
    monkeypatch.setattr("app.mobile_launcher.tailscale_cli", lambda: "/tailscale")
    responses = iter(
        [
            {"BackendState": "Running"},
            {
                "Web": {
                    TAILNET_HOST: {
                        "Handlers": {"/": {"Proxy": "http://127.0.0.1:9999"}}
                    }
                }
            },
        ]
    )
    monkeypatch.setattr("app.mobile_launcher._json_command", lambda _: next(responses))

    with pytest.raises(RuntimeError, match="尚未指向"):
        validate_mobile_environment(store)
    assert _funnel_enabled({"AllowFunnel": {TAILNET_HOST: True}})


def test_launcher_accepts_serve_host_stored_as_json_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = configured_store(tmp_path)
    monkeypatch.setattr("app.mobile_launcher.tailscale_cli", lambda: "/tailscale")
    responses = iter(
        [
            {"BackendState": "Running"},
            {
                "Web": {
                    f"{TAILNET_HOST}:443": {
                        "Handlers": {"/": {"Proxy": "http://127.0.0.1:8766"}}
                    }
                }
            },
        ]
    )
    monkeypatch.setattr("app.mobile_launcher._json_command", lambda _: next(responses))

    assert validate_mobile_environment(store) == (
        "/tailscale",
        f"https://{TAILNET_HOST}",
    )


def test_mobile_runtime_files_are_git_ignored() -> None:
    ignore = Path(".gitignore").read_text(encoding="utf-8")
    assert "mobile.db" in ignore
    assert "mobile.secret" in ignore
    assert "mobile.db-*" in ignore
