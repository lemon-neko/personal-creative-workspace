from __future__ import annotations

import base64
import re
import subprocess
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.content import semantic_revision
from app.database import connect_database
from app.main import create_app
from app.publishing import PublishingSource, WECHAT_RENDERER
from app.wechat import (
    APP_ID_ACCOUNT,
    EnvironmentCredentialStore,
    KEYCHAIN_SERVICE,
    MacOSKeychainCredentialStore,
    WechatCredentials,
    WechatOfficialClient,
    WechatPublisher,
    prepare_wechat_html,
    validate_final_wechat_content,
)
from app.workspace import create_item


class FakeCredentials:
    def __init__(self) -> None:
        self.value = WechatCredentials("wx1234567890abcdef", "s" * 32)

    def status(self):
        from app.wechat import WechatCredentialStatus

        return WechatCredentialStatus(True, "wx12…cdef", True)

    def load(self) -> WechatCredentials:
        return self.value

    def save(self, credentials: WechatCredentials) -> None:
        self.value = credentials

    def delete(self) -> None:
        self.value = WechatCredentials("", "")


def _png() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"safe-image"


def test_keychain_store_never_places_secret_in_command_arguments() -> None:
    calls: list[tuple[list[str], str | None]] = []

    def runner(arguments, **kwargs):
        calls.append((arguments, kwargs.get("input")))
        if "find-generic-password" in arguments and "-w" in arguments:
            account = arguments[arguments.index("-a") + 1]
            value = (
                "wx1234567890abcdef\n"
                if account == APP_ID_ACCOUNT
                else f"{'s' * 32}\n"
            )
            return subprocess.CompletedProcess(arguments, 0, value, "")
        return subprocess.CompletedProcess(arguments, 0, "", "")

    store = MacOSKeychainCredentialStore(runner=runner)
    store.save(WechatCredentials("wx1234567890abcdef", "s" * 32))
    loaded = store.load()

    assert loaded.app_secret == "s" * 32
    assert all("s" * 32 not in argument for call, _stdin in calls for argument in call)
    assert any(stdin == f"{'s' * 32}\n" for _call, stdin in calls)
    assert any(KEYCHAIN_SERVICE in call for call, _stdin in calls)


def test_environment_credentials_are_backend_only_compatibility(
    monkeypatch,
) -> None:
    monkeypatch.setenv("WECHAT_APP_ID", "wx1234567890abcdef")
    monkeypatch.setenv("WECHAT_APP_SECRET", "e" * 32)

    store = EnvironmentCredentialStore()
    status = store.status()
    credentials = store.load()

    assert status.configured is True
    assert status.storage == "后端环境变量"
    assert "e" * 32 not in repr(status)
    assert credentials.app_secret == "e" * 32


def test_push_html_rejects_external_images_and_changed_article_text() -> None:
    expected = '<section data-platform="wechat"><p>正文</p></section>'

    try:
        prepare_wechat_html(
            '<section data-platform="wechat"><p>正文</p><img src="https://x.test/a.png"></section>',
            expected,
        )
    except ValueError as error:
        assert "未内嵌" in str(error)
    else:
        raise AssertionError("external image should be rejected")

    try:
        prepare_wechat_html(
            '<section data-platform="wechat"><p>被替换的正文</p></section>',
            expected,
        )
    except ValueError as error:
        assert "文章版本不一致" in str(error)
    else:
        raise AssertionError("changed text should be rejected")


def test_wechat_settings_save_test_and_delete_are_explicit_posts(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(
            200, json={"access_token": "settings-token", "expires_in": 7200}
        )

    credentials = FakeCredentials()
    application = create_app(content_root=tmp_path, enable_scheduler=False)
    application.state.wechat = WechatPublisher(
        tmp_path,
        tmp_path,
        credentials=credentials,
        client=WechatOfficialClient(httpx.MockTransport(handler)),
    )
    with TestClient(application) as client:
        page = client.get("/settings/wechat")
        saved = client.post(
            "/settings/wechat/credentials",
            data={"app_id": "wx1234567890abcdef", "app_secret": "z" * 32},
            follow_redirects=False,
        )
        tested = client.post("/settings/wechat/test", follow_redirects=False)
        deleted = client.post(
            "/settings/wechat/credentials/delete", follow_redirects=False
        )

    assert page.status_code == 200 and "macOS 钥匙串" in page.text
    assert "测试凭证、白名单与草稿权限" in page.text
    assert saved.status_code == tested.status_code == deleted.status_code == 303
    assert calls == ["/cgi-bin/token", "/cgi-bin/draft/count"]


def test_publish_page_preflight_and_confirm_create_one_wechat_draft(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/cgi-bin/token":
            return httpx.Response(
                200, json={"access_token": "test-token", "expires_in": 7200}
            )
        if request.url.path == "/cgi-bin/media/uploadimg":
            return httpx.Response(200, json={"url": "http://mmbiz.example/body.png"})
        if request.url.path == "/cgi-bin/material/add_material":
            return httpx.Response(200, json={"media_id": "cover-media"})
        if request.url.path == "/cgi-bin/draft/add":
            assert b"cover-media" in request.content
            assert b'"need_open_comment":1' in request.content
            return httpx.Response(200, json={"media_id": "draft-media"})
        raise AssertionError(request.url)

    application = create_app(content_root=tmp_path, enable_scheduler=False)
    application.state.wechat = WechatPublisher(
        tmp_path,
        tmp_path,
        credentials=FakeCredentials(),
        client=WechatOfficialClient(httpx.MockTransport(handler)),
    )
    item = create_item(
        tmp_path,
        title="一篇虚构测试文章",
        body="## 小节\n\n正文内容。\n\n![配图](/assets/body.png)",
        kind="article",
    )
    assets = tmp_path / "assets"
    assets.mkdir(exist_ok=True)
    (assets / "cover.png").write_bytes(_png())
    (assets / "body.png").write_bytes(_png())
    rendered = WECHAT_RENDERER.render(
        PublishingSource(item.id, item.kind, item.title, item.summary, item.body)
    )

    with TestClient(application) as client:
        page = client.get(f"/publish/{item.id}")
        assert page.status_code == 200
        assert "草稿箱直推" in page.text
        preflight = client.post(
            f"/publish/{item.id}/wechat/preflight",
            data={
                "article_revision": semantic_revision(item),
                "title": item.title,
                "author": "羽白",
                "digest": item.summary,
                "source_url": "",
                "final_html": rendered.export_html.replace(
                    'src="/assets/body.png"',
                    f'src="data:image/png;base64,{base64.b64encode(_png()).decode()}"',
                ),
                "cover_asset": "cover.png",
                "formula_count": "0",
                "image_fallback_count": "0",
                "formula_fallback_count": "0",
                "primary_color": "#1199aa",
                "font_size": "16",
                "font_family": "system",
                "indent": "0",
                "justify": "1",
            },
        )
        assert preflight.status_code == 200
        assert "确认创建公众号草稿" in preflight.text
        matched = re.search(r'name="intent_id" value="([0-9a-f]{32})"', preflight.text)
        assert matched is not None
        confirmed = client.post(
            f"/publish/{item.id}/wechat/confirm",
            data={"intent_id": matched.group(1)},
        )

    assert confirmed.status_code == 200
    assert "草稿已创建" in confirmed.text
    assert "draft-media" in confirmed.text
    assert calls == [
        "/cgi-bin/token",
        "/cgi-bin/media/uploadimg",
        "/cgi-bin/material/add_material",
        "/cgi-bin/draft/add",
    ]
    with connect_database(tmp_path / "workspace.db") as connection:
        row = connection.execute(
            "SELECT status,media_id FROM wechat_draft_pushes"
        ).fetchone()
        columns = {
            value[1]
            for value in connection.execute(
                "PRAGMA table_info(wechat_draft_pushes)"
            ).fetchall()
        }
    assert (row["status"], row["media_id"]) == ("succeeded", "draft-media")
    assert "final_html" not in columns and "app_secret" not in columns


def test_draft_timeout_is_recorded_as_unknown_without_retry(tmp_path: Path) -> None:
    draft_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal draft_calls
        if request.url.path == "/cgi-bin/token":
            return httpx.Response(200, json={"access_token": "token"})
        if request.url.path == "/cgi-bin/material/add_material":
            return httpx.Response(200, json={"media_id": "cover"})
        if request.url.path == "/cgi-bin/draft/add":
            draft_calls += 1
            raise httpx.ReadTimeout("unknown", request=request)
        raise AssertionError(request.url)

    publisher = WechatPublisher(
        tmp_path,
        tmp_path,
        credentials=FakeCredentials(),
        client=WechatOfficialClient(httpx.MockTransport(handler)),
    )
    (tmp_path / "assets").mkdir(exist_ok=True)
    (tmp_path / "assets" / "cover.png").write_bytes(_png())
    html = '<section data-platform="wechat"><p>正文</p></section>'
    intent, _existing = publisher.prepare_intent(
        article_id="article-1",
        article_revision="a" * 64,
        title="测试",
        author="羽白",
        digest="",
        source_url="",
        final_html=html,
        expected_html=html,
        cover_asset="cover.png",
        formula_count=0,
    )

    import asyncio

    result = asyncio.run(
        publisher.push(intent, current_revision="a" * 64)
    )
    repeated = asyncio.run(
        publisher.push(intent, current_revision="a" * 64)
    )

    assert result.status == "unknown"
    assert result.error_code == "timeout"
    assert repeated.id == result.id
    assert draft_calls == 1


def test_invalid_access_token_is_refreshed_and_failed_operation_retried_once(
    tmp_path: Path,
) -> None:
    token_calls = 0
    image_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls, image_calls
        if request.url.path == "/cgi-bin/token":
            token_calls += 1
            return httpx.Response(
                200,
                json={"access_token": f"token-{token_calls}", "expires_in": 7200},
            )
        if request.url.path == "/cgi-bin/media/uploadimg":
            image_calls += 1
            if image_calls == 1:
                return httpx.Response(
                    200, json={"errcode": 40014, "errmsg": "invalid token"}
                )
            assert request.url.params["access_token"] == "token-2"
            return httpx.Response(200, json={"url": "https://mmbiz.qpic.cn/body"})
        if request.url.path == "/cgi-bin/material/add_material":
            assert request.url.params["access_token"] == "token-2"
            return httpx.Response(200, json={"media_id": "cover"})
        if request.url.path == "/cgi-bin/draft/add":
            assert request.url.params["access_token"] == "token-2"
            return httpx.Response(200, json={"media_id": "draft"})
        raise AssertionError(request.url)

    publisher = WechatPublisher(
        tmp_path,
        tmp_path,
        credentials=FakeCredentials(),
        client=WechatOfficialClient(httpx.MockTransport(handler)),
    )
    (tmp_path / "assets").mkdir(exist_ok=True)
    (tmp_path / "assets" / "cover.png").write_bytes(_png())
    data_url = f"data:image/png;base64,{base64.b64encode(_png()).decode()}"
    html = f'<section data-platform="wechat"><p>正文</p><img src="{data_url}"></section>'
    intent, _existing = publisher.prepare_intent(
        article_id="article-token-refresh",
        article_revision="b" * 64,
        title="测试刷新",
        author="羽白",
        digest="",
        source_url="",
        final_html=html,
        expected_html=html,
        cover_asset="cover.png",
        formula_count=0,
    )

    import asyncio

    result = asyncio.run(publisher.push(intent, current_revision="b" * 64))

    assert result.status == "succeeded"
    assert (token_calls, image_calls) == (2, 2)


def test_wechat_cdn_images_are_preserved_without_reupload() -> None:
    html = (
        '<section data-platform="wechat"><p>正文</p>'
        '<img src="https://mmbiz.qpic.cn/example/image.png"></section>'
    )

    prepared = prepare_wechat_html(html, html)

    assert prepared.images == ()
    assert "https://mmbiz.qpic.cn/example/image.png" in prepared.html


def test_permission_error_explains_48001_is_an_account_permission_issue() -> None:
    from app.wechat import WechatAPIError

    error = WechatAPIError("检查草稿接口权限", "48001")

    assert "没有所调用接口的权限" in str(error)
    assert "通常不是代码故障" in str(error)


def test_final_wechat_content_enforces_official_size_boundary() -> None:
    validate_final_wechat_content("<p>安全正文</p>")

    try:
        validate_final_wechat_content("字" * 20_001)
    except ValueError as error:
        assert "20000" in str(error)
    else:
        raise AssertionError("oversized content should be rejected")
