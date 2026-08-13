from __future__ import annotations

from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from app.content import load_items
from app.main import create_app
from app.video import VideoProjectRepository
from app.workspace import create_item, items_directory


def test_video_handoff_copies_only_private_workspace_images(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "cover.png").write_bytes(b"\x89PNG\r\n\x1a\nprivate-image")
    article = create_item(
        tmp_path,
        title="AI 产业链与 Vibe Coding",
        kind="article",
        body=(
            "开场正文。\n\n"
            "![本地配图](/assets/cover.png)\n\n"
            "![外部图片](https://example.com/tracker.png)\n\n"
            "![本地文件](file:///etc/passwd)"
        ),
    )
    original = article.source.read_text(encoding="utf-8")
    repository = VideoProjectRepository(tmp_path, tmp_path)

    project = repository.create(article, notes="做成 90 秒横屏视频")

    assert project.status == "planning"
    assert len(project.assets) == 1
    assert project.assets[0].stored_name == "asset-01.png"
    assert (project.directory / "assets" / "asset-01.png").read_bytes().endswith(
        b"private-image"
    )
    brief = project.brief_path.read_text(encoding="utf-8")
    assert "![本地配图](assets/asset-01.png)" in brief
    assert "https://example.com/tracker.png" in brief
    assert "file:///etc/passwd" in brief
    assert article.source.read_text(encoding="utf-8") == original
    assert (project.directory.stat().st_mode & 0o777) == 0o700
    assert (project.brief_path.stat().st_mode & 0o777) == 0o600

    manifest = yaml.safe_load(
        (project.directory / "manifest.yaml").read_text(encoding="utf-8")
    )
    assert manifest["source_id"] == article.id
    assert manifest["assets"][0]["source_url"] == "/assets/cover.png"


def test_video_repository_status_and_path_boundaries(tmp_path: Path) -> None:
    article = create_item(tmp_path, title="测试文章", kind="article", body="正文。")
    repository = VideoProjectRepository(tmp_path, tmp_path)
    project = repository.create(article)

    updated = repository.update_status(project.id, "editing")

    assert updated.status == "editing"
    assert repository.resolve_file(project.id, "brief.md") == project.brief_path
    assert repository.resolve_file(project.id, "../manifest.yaml") is None
    assert repository.resolve_file(project.id, "/etc/passwd") is None
    assert repository.resolve_file("../../outside", "brief.md") is None


def test_video_studio_routes_create_handoff_and_protect_files(tmp_path: Path) -> None:
    article = create_item(
        tmp_path,
        title="可以变成视频的文章",
        kind="article",
        body="第一段。\n\n第二段。",
    )
    thought = create_item(tmp_path, title="普通想法", body="暂时不是文章。")
    client = TestClient(create_app(content_root=tmp_path, enable_scheduler=False))

    page = client.get("/video")
    created = client.post(
        "/video/projects",
        data={"source_id": article.id, "notes": "保留一点抽象感"},
        follow_redirects=True,
    )
    repository = VideoProjectRepository(tmp_path, tmp_path)
    project = repository.projects()[0]
    brief = client.get(f"/video/projects/{project.id}/files/brief.md")
    updated = client.post(
        f"/video/projects/{project.id}/status",
        data={"status": "exported"},
        follow_redirects=True,
    )
    rejected = client.post(
        "/video/projects",
        data={"source_id": thought.id},
    )

    assert page.status_code == 200
    assert "视频创作" in page.text
    assert "OpenCut" in page.text
    assert "可以变成视频的文章" in page.text
    assert "普通想法" not in page.text
    assert created.status_code == 200
    assert "视频交接包已生成" in created.text
    assert brief.status_code == 200
    assert "可以变成视频的文章" in brief.text
    assert updated.status_code == 200
    assert "已导出" in updated.text
    assert rejected.status_code == 422
    assert "只能从文章草稿或已成稿创建" in rejected.text
    assert client.get(f"/video/projects/{project.id}/files/../manifest.yaml").status_code == 404
    assert client.get("/video/projects/not-a-project/files/brief.md").status_code == 404


def test_video_handoff_does_not_change_content_collection(tmp_path: Path) -> None:
    article = create_item(tmp_path, title="唯一文章", kind="article", body="原始正文。")
    before = load_items(items_directory(tmp_path)).get(article.id)

    VideoProjectRepository(tmp_path, tmp_path).create(article)

    after = load_items(items_directory(tmp_path)).get(article.id)
    assert after == before
