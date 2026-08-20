from __future__ import annotations

from pathlib import Path

import pytest

from app.backup import create_encrypted_backup
from app.career import CareerRepository
from app.privacy import prepare_private_root
from app.recovery import create_inventory, exercise_restore, write_inventory
from app.workspace import create_item


def test_inventory_and_isolated_restore_match_private_payload(tmp_path: Path) -> None:
    source = prepare_private_root(tmp_path / "source")
    CareerRepository(source).save_profile(target_roles="Example role")
    create_item(source / "content", body="只用于恢复测试的虚构记录。")
    archive = tmp_path / "backup.zip"
    create_encrypted_backup(source, "a-long-password", archive)

    before = create_inventory(source)
    target = tmp_path / "isolated"
    restored = exercise_restore(archive, "a-long-password", target)
    anchor = write_inventory(restored, tmp_path / "anchor.json")

    assert restored.markdown_files == before.markdown_files == 1
    assert restored.database_files == before.database_files == 1
    assert restored.schema_versions == before.schema_versions
    assert create_inventory(target).aggregate_sha256 == restored.aggregate_sha256
    assert anchor.stat().st_mode & 0o777 == 0o600
    assert "只用于恢复测试" not in anchor.read_text(encoding="utf-8")


def test_isolated_restore_refuses_non_empty_target(tmp_path: Path) -> None:
    target = tmp_path / "occupied"
    target.mkdir()
    (target / "keep.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="不存在或为空"):
        exercise_restore(tmp_path / "missing.zip", "a-long-password", target)
