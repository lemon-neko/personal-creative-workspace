"""Private source-material inbox. URLs are stored but never fetched."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import yaml

from app.workspace import SHANGHAI


MATERIAL_STATUSES = {"inbox", "reading", "read"}
MATERIAL_TYPES = {"note", "url", "document"}


@dataclass(frozen=True)
class SourceMaterial:
    id: str
    title: str
    source_type: str
    status: str
    body: str
    source_url: str | None
    document_id: str | None
    created_at: datetime
    updated_at: datetime
    source: Path


def materials_directory(content_root: Path) -> Path:
    return content_root / "sources" / "materials"


def _safe_url(value: str) -> str | None:
    if not value.strip():
        return None
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("来源链接必须是有效的 HTTP(S) 地址")
    return value.strip()[:2000]


def create_material(
    content_root: Path,
    *,
    title: str,
    body: str = "",
    source_type: str = "note",
    source_url: str = "",
    document_id: str = "",
    status: str = "inbox",
) -> SourceMaterial:
    if source_type not in MATERIAL_TYPES or status not in MATERIAL_STATUSES:
        raise ValueError("材料类型或状态无效")
    if not title.strip():
        raise ValueError("材料标题不能为空")
    cleaned_url = _safe_url(source_url)
    if source_type == "url" and not cleaned_url:
        raise ValueError("链接材料必须填写来源链接")
    if source_type == "document" and not document_id.strip():
        raise ValueError("文档材料必须关联本地文档")
    now = datetime.now(SHANGHAI).replace(microsecond=0)
    material_id = f"material-{uuid4().hex[:12]}"
    metadata = {
        "id": material_id,
        "title": title.strip()[:180],
        "source_type": source_type,
        "status": status,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    if cleaned_url:
        metadata["source_url"] = cleaned_url
    if document_id.strip():
        metadata["document_id"] = document_id.strip()[:160]
    path = materials_directory(content_root) / f"{material_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    front = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()
    path.write_text(f"---\n{front}\n---\n\n{body.strip()}\n", encoding="utf-8")
    path.chmod(0o600)
    return parse_material(path)


def parse_material(path: Path) -> SourceMaterial:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("材料缺少 front matter")
    try:
        end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as error:
        raise ValueError("材料缺少 front matter 结束标记") from error
    metadata = yaml.safe_load("\n".join(lines[1:end]))
    if not isinstance(metadata, dict):
        raise ValueError("材料 front matter 无效")
    source_type = metadata.get("source_type")
    status = metadata.get("status")
    if source_type not in MATERIAL_TYPES or status not in MATERIAL_STATUSES:
        raise ValueError("材料类型或状态无效")
    created = datetime.fromisoformat(str(metadata.get("created_at")))
    updated = datetime.fromisoformat(str(metadata.get("updated_at")))
    if created.tzinfo is None:
        created = created.replace(tzinfo=SHANGHAI)
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=SHANGHAI)
    title = str(metadata.get("title", "")).strip()
    material_id = str(metadata.get("id", "")).strip()
    if not title or not material_id:
        raise ValueError("材料 ID 或标题为空")
    return SourceMaterial(
        id=material_id,
        title=title,
        source_type=source_type,
        status=status,
        body="\n".join(lines[end + 1 :]).strip(),
        source_url=(str(metadata.get("source_url", "")).strip() or None),
        document_id=(str(metadata.get("document_id", "")).strip() or None),
        created_at=created.astimezone(SHANGHAI),
        updated_at=updated.astimezone(SHANGHAI),
        source=path,
    )


def load_materials(content_root: Path) -> tuple[SourceMaterial, ...]:
    materials: list[SourceMaterial] = []
    for path in sorted(materials_directory(content_root).glob("*.md")):
        try:
            materials.append(parse_material(path))
        except (OSError, UnicodeError, ValueError, yaml.YAMLError):
            continue
    return tuple(sorted(materials, key=lambda item: item.updated_at, reverse=True))


def update_material_status(
    content_root: Path,
    material_id: str,
    status: str,
) -> SourceMaterial:
    if status not in MATERIAL_STATUSES:
        raise ValueError("材料状态无效")
    material = next(
        (item for item in load_materials(content_root) if item.id == material_id),
        None,
    )
    if material is None:
        raise KeyError(material_id)
    updated = replace(
        material,
        status=status,
        updated_at=datetime.now(SHANGHAI).replace(microsecond=0),
    )
    metadata = {
        "id": updated.id,
        "title": updated.title,
        "source_type": updated.source_type,
        "status": updated.status,
        "created_at": updated.created_at.isoformat(),
        "updated_at": updated.updated_at.isoformat(),
    }
    if updated.source_url:
        metadata["source_url"] = updated.source_url
    if updated.document_id:
        metadata["document_id"] = updated.document_id
    front = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()
    updated.source.write_text(
        f"---\n{front}\n---\n\n{updated.body.strip()}\n",
        encoding="utf-8",
    )
    updated.source.chmod(0o600)
    return parse_material(updated.source)
