from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.content import load_items, semantic_revision
from app.knowledge_store import (
    KnowledgeEdge,
    create_knowledge_card,
    create_knowledge_map,
    load_knowledge_store,
    supersede_knowledge_card,
)
from app.main import create_app
from app.mobile import MobileCaptureService, MobileStore, OfflineCapture
from app.mobile_launcher import _funnel_enabled, validate_mobile_environment
from app.mobile_main import _is_same_tailnet_origin, create_mobile_app
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


def knowledge_fixture(tmp_path: Path) -> dict[str, object]:
    content_root = tmp_path / "content"
    source = create_item(
        content_root,
        body=(
            "这是可用于手机溯源的简短概览，说明这条记录讨论 Agent 可靠性、"
            "可验证边界和工程约束。为了让摘要只保留最小必要信息，这里继续补充"
            "一些不涉及隐私的背景说明：系统需要明确输入、输出、失败恢复、权限"
            "边界和人工确认，同时保证每个结论都能追溯到已经确认的证据。\n\n"
            "这段绝密原始正文不应该出现在手机知识页。"
        ),
        title="关于可靠性的原始想法",
        tags="Agent,可靠性",
        item_id="source-private-thought",
    )
    technology = create_knowledge_map(
        content_root,
        title="技术",
        kind="subject",
        summary="关注软件、模型与工程系统。",
    )
    philosophy = create_knowledge_map(
        content_root,
        title="哲学",
        kind="subject",
        summary="追问概念、边界与判断依据。",
    )
    memory = create_knowledge_map(
        content_root,
        title="Agent 记忆",
        kind="topic",
        summary="连接 Agent 工程与认知理解。",
        parent_ids=(technology.id, philosophy.id),
    )
    old_card = create_knowledge_card(
        content_root,
        title="旧的可靠性判断",
        body="旧观点会保留，但不进入默认有效卡列表。",
        card_type="claim",
        subjects=("技术",),
        source_ids=(source.id,),
        map_ids=(memory.id,),
    )
    relative_old = old_card.source.relative_to(content_root).as_posix()
    current_card = create_knowledge_card(
        content_root,
        title="可靠性来自可验证的边界",
        body=(
            "## 核心判断\n\n可靠性不是相信模型，而是验证每一步。\n\n"
            f"[查看历史知识]({relative_old})\n\n"
            f"[桌面来源](sources/thoughts/{source.source.name})\n\n"
            f"[桌面管理](/ideas/{source.id})\n\n"
            "![私有配图](/assets/private.png)\n\n"
            "<script>alert('raw')</script>\n\n"
            "[危险链接](javascript:alert('x'))"
        ),
        card_type="claim",
        subjects=("技术", "哲学"),
        source_ids=(source.id,),
        map_ids=(memory.id,),
        concepts=("可靠性", "验证"),
        relations=(KnowledgeEdge(old_card.id, "extends", "补充验证边界"),),
    )
    retired = supersede_knowledge_card(content_root, old_card.id, current_card.id)
    return {
        "source": source,
        "technology": technology,
        "philosophy": philosophy,
        "memory": memory,
        "old_card": retired,
        "current_card": current_card,
    }


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
    assert "isKnowledgePath(url.pathname)" in worker.text
    assert "yubai-mobile-shell-v6" in worker.text
    assert "yubai-mobile-knowledge-v1" in worker.text
    assert 'styles/base.css?v=6' in worker.text
    assert 'styles/knowledge.css?v=6' in worker.text
    assert 'mobile.js?v=6' in worker.text
    assert "CACHE_KNOWLEDGE_PATHS" in worker.text
    assert "CLEAR_KNOWLEDGE_CACHE" in worker.text
    assert "self.skipWaiting()" in worker.text
    assert "self.clients.claim()" in worker.text
    assert 'caches.match("/offline")' in worker.text
    assert "syncWorkspace()" in worker.text
    assert "ideaEdits" in worker.text
    assert 'isIdeaPath(url.pathname)' in worker.text
    assert "registration.sync.register" in client.get("/mobile-assets/mobile.js").text
    assert "capture-form" in client.get("/offline").text


def test_mobile_knowledge_requires_an_active_paired_device(tmp_path: Path) -> None:
    fixture = knowledge_fixture(tmp_path)
    client, store = mobile_client(tmp_path)

    unpaired_pages = tuple(
        client.get(path, follow_redirects=False)
        for path in (
            "/knowledge",
            f"/knowledge/maps/{fixture['technology'].id}",
            f"/knowledge/cards/{fixture['current_card'].id}",
        )
    )
    pair(client, store)
    paired = client.get("/knowledge")
    store.revoke_device(store.devices()[0].id)
    revoked = client.get("/knowledge", follow_redirects=False)

    assert all(
        page.status_code == 303 and page.headers["location"] == "/"
        for page in unpaired_pages
    )
    assert paired.status_code == 200
    assert revoked.status_code == 303 and revoked.headers["location"] == "/"


def test_mobile_knowledge_overview_shows_layered_active_content(
    tmp_path: Path,
) -> None:
    fixture = knowledge_fixture(tmp_path)
    client, store = mobile_client(tmp_path)
    pair(client, store)

    page = client.get("/knowledge")

    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    assert page.headers["x-pcw-offline-knowledge"] == "1"
    assert "羽白工作台" in page.text
    assert "随手记" in page.text and "知识库" in page.text
    assert "2</strong><span>学科" in page.text
    assert "1</strong><span>主题" in page.text
    assert "1</strong><span>有效卡片" in page.text
    assert "Agent 记忆" in page.text
    assert "可靠性来自可验证的边界" in page.text
    assert f"/knowledge/maps/{fixture['memory'].id}" in page.text
    assert f"/knowledge/cards/{fixture['current_card'].id}" in page.text
    assert "knowledge-offline-manifest" in page.text
    assert "清除离线副本" in page.text
    assert fixture["old_card"].title not in page.text


def test_mobile_subject_map_aggregates_multi_parent_topic_cards(
    tmp_path: Path,
) -> None:
    fixture = knowledge_fixture(tmp_path)
    client, store = mobile_client(tmp_path)
    pair(client, store)

    technology = client.get(f"/knowledge/maps/{fixture['technology'].id}")
    philosophy = client.get(f"/knowledge/maps/{fixture['philosophy'].id}")
    topic = client.get(f"/knowledge/maps/{fixture['memory'].id}")

    for page in (technology, philosophy, topic):
        assert page.status_code == 200
        assert page.headers["x-pcw-offline-knowledge"] == "1"
        assert "可靠性来自可验证的边界" in page.text
        assert "旧的可靠性判断" not in page.text
    assert "聚合知识卡" in technology.text
    assert "直接知识卡" in topic.text
    assert "技术" in topic.text and "哲学" in topic.text


def test_mobile_card_projects_safe_markdown_and_minimal_sources(
    tmp_path: Path,
) -> None:
    fixture = knowledge_fixture(tmp_path)
    client, store = mobile_client(tmp_path)
    pair(client, store)
    current = fixture["current_card"]

    page = client.get(f"/knowledge/cards/{current.id}")

    assert page.status_code == 200
    assert page.headers["x-pcw-offline-knowledge"] == "1"
    assert "可靠性不是相信模型" in page.text
    assert f"/knowledge/cards/{fixture['old_card'].id}" in page.text
    assert "关于可靠性的原始想法" in page.text
    assert fixture["source"].summary in page.text
    assert "这段绝密原始正文" not in page.text
    assert "/ideas/" not in page.text
    assert "/assets/private.png" not in page.text
    assert "javascript:" not in page.text
    assert "&lt;script&gt;" in page.text
    assert "私有配图仅可在桌面查看" in page.text


def test_mobile_superseded_card_links_to_replacement(tmp_path: Path) -> None:
    fixture = knowledge_fixture(tmp_path)
    client, store = mobile_client(tmp_path)
    pair(client, store)

    page = client.get(f"/knowledge/cards/{fixture['old_card'].id}")

    assert page.status_code == 200
    assert "已被替代" in page.text
    assert "当前版本" in page.text
    assert f"/knowledge/cards/{fixture['current_card'].id}" in page.text


def test_mobile_knowledge_unknown_ids_use_private_404(tmp_path: Path) -> None:
    client, store = mobile_client(tmp_path)
    pair(client, store)

    missing_map = client.get("/knowledge/maps/not-found")
    missing_card = client.get("/knowledge/cards/not-found")

    assert missing_map.status_code == 404
    assert missing_card.status_code == 404
    assert "x-pcw-offline-knowledge" not in missing_map.headers
    assert "x-pcw-offline-knowledge" not in missing_card.headers
    assert "这条知识不在这里" in missing_map.text
    assert "这条知识不在这里" in missing_card.text


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
    assert "想法会长大" in client.get("/ideas").text
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


def test_mobile_manual_distill_requires_topic_and_records_source_revision(
    tmp_path: Path,
) -> None:
    fixture = knowledge_fixture(tmp_path)
    source = fixture["source"]
    client, store = mobile_client(tmp_path)
    csrf = pair(client, store)
    payload = {
        "title": "可靠性需要逐步验证",
        "body": "把每一步变成可验证的状态，而不是依赖一次性成功。",
        "card_type": "method",
        "concepts": "可靠性,验证",
    }

    missing_topic = client.post(
        f"/api/ideas/{source.id}/knowledge/cards",
        data=payload,
        headers={"x-csrf-token": csrf},
    )
    created = client.post(
        f"/api/ideas/{source.id}/knowledge/cards",
        data={**payload, "map_ids": [fixture["memory"].id]},
        headers={"x-csrf-token": csrf},
    )

    assert missing_topic.status_code == 422
    assert created.status_code == 201
    card = load_knowledge_store(tmp_path / "content").card(created.json()["card_id"])
    assert card.source_ids == (source.id,)
    assert card.map_ids == (fixture["memory"].id,)
    assert set(card.subjects) == {"技术", "哲学"}
    assert card.source_revisions[source.id] == semantic_revision(source)


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
