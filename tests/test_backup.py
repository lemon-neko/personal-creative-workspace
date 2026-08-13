from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.backup import (
    create_encrypted_backup,
    inspect_encrypted_backup,
    restore_encrypted_backup,
)
from app.career import CareerRepository
from app.migrate_private_data import apply_migration, plan_migration
from app.main import create_app
from app.privacy import prepare_private_root
from app.workspace import create_item


def test_aes_backup_verifies_and_restores_private_data(tmp_path: Path) -> None:
    data_root = prepare_private_root(tmp_path / "private")
    repository = CareerRepository(data_root)
    repository.save_profile(target_roles="AI Engineer")
    item = create_item(data_root / "content", body="不会进入 Git 的想法。")
    video_project = data_root / "video-projects" / "video-test"
    video_project.mkdir()
    (video_project / "brief.md").write_text("私有视频交接稿", encoding="utf-8")
    archive = tmp_path / "workspace.zip"

    created = create_encrypted_backup(data_root, "a-long-password", archive)
    preview = inspect_encrypted_backup(archive, "a-long-password")
    item.source.unlink()
    rollback = restore_encrypted_backup(archive, "a-long-password", data_root)

    assert created.file_count == preview.file_count == 3
    assert item.source.name in {Path(name).name for name in preview.files}
    assert "video-projects/video-test/brief.md" in preview.files
    assert item.source.exists()
    assert (data_root / "video-projects" / "video-test" / "brief.md").exists()
    assert rollback.exists()
    with pytest.raises(ValueError, match="口令错误|损坏"):
        inspect_encrypted_backup(archive, "wrong-password")


def test_backup_rejects_short_password(tmp_path: Path) -> None:
    data_root = prepare_private_root(tmp_path / "private")
    CareerRepository(data_root)
    with pytest.raises(ValueError, match="至少"):
        create_encrypted_backup(data_root, "short", tmp_path / "bad.zip")


def test_backup_routes_export_and_preview_without_persisting_password(
    tmp_path: Path,
) -> None:
    app = create_app(
        content_root=tmp_path / "content",
        data_root=tmp_path,
        enable_scheduler=False,
        enforce_security=False,
    )
    create_item(app.state.content_root, body="备份路由内容")
    client = TestClient(app)

    exported = client.post(
        "/settings/backups/export",
        data={"password": "route-password"},
    )
    preview = client.post(
        "/settings/backups/inspect",
        data={"password": "route-password"},
        files={"upload": ("backup.zip", exported.content, "application/zip")},
    )

    assert exported.status_code == 200
    assert exported.headers["content-type"] == "application/zip"
    assert "恢复预演" in preview.text
    assert 'type="password" name="password"' in preview.text
    assert 'value="route-password"' not in preview.text


def test_legacy_migration_is_dry_run_idempotent_and_detects_conflict(
    tmp_path: Path,
) -> None:
    source = tmp_path / "legacy"
    destination = tmp_path / "private"
    create_item(source, body="旧内容")

    first = plan_migration(source, destination)
    assert {entry.action for entry in first} == {"copy"}
    assert not first[0].destination.exists()

    prepare_private_root(destination)
    apply_migration(first)
    second = plan_migration(source, destination)
    assert {entry.action for entry in second} == {"unchanged"}

    target = first[0].destination
    target.write_text("different", encoding="utf-8")
    conflict = plan_migration(source, destination)
    assert conflict[0].action == "conflict"
    with pytest.raises(ValueError, match="同名文件"):
        apply_migration(conflict)
