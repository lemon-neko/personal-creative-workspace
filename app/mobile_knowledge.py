"""Read-only, privacy-minimised knowledge projections for the mobile PWA."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt

from app.content import ContentItem, load_items
from app.knowledge_store import KnowledgeCard, KnowledgeMap, KnowledgeStore


MOBILE_MARKDOWN = (
    MarkdownIt(
        "commonmark",
        {
            "html": False,
            "linkify": True,
            "typographer": True,
        },
    )
    .enable("table")
    .enable("strikethrough")
)

RELATION_LABELS = {
    "related": "相关",
    "extends": "延伸",
    "supports": "支持",
    "contrasts": "对照",
}
CARD_TYPE_LABELS = {
    "concept": "概念",
    "claim": "判断",
    "question": "问题",
    "method": "方法",
    "observation": "观察",
}
CARD_STATUS_LABELS = {
    "active": "当前有效",
    "superseded": "已被替代",
    "archived": "已归档",
}
DANGEROUS_SCHEME_RE = re.compile(r"(?i)\b(javascript|data|vbscript)\s*:")


@dataclass(frozen=True)
class MobileSourceSummary:
    """The only source fields a paired phone may receive."""

    id: str
    title: str
    summary: str
    created_at: datetime


@dataclass(frozen=True)
class MobileRelation:
    target_id: str
    title: str
    relation: str
    relation_label: str
    note: str
    href: str | None
    target_type: str


def active_cards(store: KnowledgeStore) -> tuple[KnowledgeCard, ...]:
    return tuple(card for card in store.cards if card.status == "active")


def child_maps(store: KnowledgeStore, map_id: str) -> tuple[KnowledgeMap, ...]:
    return tuple(item for item in store.maps if map_id in item.parent_ids)


def descendant_map_ids(store: KnowledgeStore, map_id: str) -> frozenset[str]:
    """Return all recursive children without assuming a single-parent tree."""

    descendants: set[str] = set()
    pending = [map_id]
    while pending:
        parent = pending.pop()
        for child in child_maps(store, parent):
            if child.id in descendants or child.id == map_id:
                continue
            descendants.add(child.id)
            pending.append(child.id)
    return frozenset(descendants)


def cards_for_map(
    store: KnowledgeStore,
    map_item: KnowledgeMap,
) -> tuple[KnowledgeCard, ...]:
    """Aggregate active descendant cards for subjects and direct cards for topics."""

    map_ids = {map_item.id}
    if map_item.kind == "subject":
        map_ids.update(descendant_map_ids(store, map_item.id))
    return tuple(
        card for card in active_cards(store) if map_ids.intersection(card.map_ids)
    )


def latest_knowledge_update(store: KnowledgeStore) -> datetime | None:
    values = [item.updated_at for item in store.maps]
    values.extend(card.updated_at for card in active_cards(store))
    return max(values) if values else None


def source_summaries(
    content_root: Path,
    card: KnowledgeCard,
) -> tuple[MobileSourceSummary, ...]:
    """Resolve provenance without exposing source body, file path, or desktop route."""

    items = {item.id: item for item in load_items(content_root).items}
    return tuple(
        MobileSourceSummary(item.id, item.title, item.summary, item.created_at)
        for source_id in card.source_ids
        if (item := items.get(source_id)) is not None
    )


def relation_projections(
    content_root: Path,
    store: KnowledgeStore,
    card: KnowledgeCard,
) -> tuple[MobileRelation, ...]:
    source_items: dict[str, ContentItem] = {
        item.id: item for item in load_items(content_root).items
    }
    cards = {item.id: item for item in store.cards}
    maps = {item.id: item for item in store.maps}
    projections: list[MobileRelation] = []
    for edge in card.relations:
        if target := cards.get(edge.target_id):
            projections.append(
                MobileRelation(
                    edge.target_id,
                    target.title,
                    edge.relation,
                    RELATION_LABELS[edge.relation],
                    edge.note,
                    f"/knowledge/cards/{target.id}",
                    "知识卡",
                )
            )
        elif target_map := maps.get(edge.target_id):
            projections.append(
                MobileRelation(
                    edge.target_id,
                    target_map.title,
                    edge.relation,
                    RELATION_LABELS[edge.relation],
                    edge.note,
                    f"/knowledge/maps/{target_map.id}",
                    "知识地图",
                )
            )
        elif source := source_items.get(edge.target_id):
            projections.append(
                MobileRelation(
                    edge.target_id,
                    source.title,
                    edge.relation,
                    RELATION_LABELS[edge.relation],
                    edge.note,
                    None,
                    "原始来源",
                )
            )
    return tuple(projections)


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _knowledge_href(
    raw: str,
    *,
    source: Path | None,
    content_root: Path,
    store: KnowledgeStore,
) -> str | None:
    parsed = urlsplit(raw)
    scheme = parsed.scheme.casefold()
    if scheme:
        return raw if scheme in {"http", "https", "mailto"} else None
    if parsed.netloc:
        return None
    path_value = unquote(parsed.path)
    fragment = f"#{parsed.fragment}" if parsed.fragment else ""
    if not path_value:
        return fragment or None
    if path_value.startswith("/knowledge/cards/"):
        card_id = path_value.removeprefix("/knowledge/cards/").split("/", 1)[0]
        return f"/knowledge/cards/{card_id}{fragment}" if store.card(card_id) else None
    if path_value.startswith("/knowledge/maps/"):
        map_id = path_value.removeprefix("/knowledge/maps/").split("/", 1)[0]
        return f"/knowledge/maps/{map_id}{fragment}" if store.map(map_id) else None
    if not path_value.casefold().endswith(".md"):
        return None

    candidates = [content_root / path_value.lstrip("/")]
    if source is not None:
        candidates.append(source.parent / path_value)
    candidate = next(
        (
            item.resolve()
            for item in candidates
            if _inside(content_root, item) and item.is_file()
        ),
        None,
    )
    if candidate is None:
        return None
    for card in store.cards:
        if card.source.resolve() == candidate:
            return f"/knowledge/cards/{card.id}{fragment}"
    for item in store.maps:
        if item.source.resolve() == candidate:
            return f"/knowledge/maps/{item.id}{fragment}"
    return None


def _as_empty_text(token) -> None:
    token.type = "text"
    token.tag = ""
    token.nesting = 0
    token.content = ""
    token.attrs = {}
    token.children = None


def _project_tokens(
    tokens: list,
    *,
    source: Path | None,
    content_root: Path,
    store: KnowledgeStore,
) -> None:
    stripped_links: list[bool] = []
    for token in tokens:
        children = getattr(token, "children", None)
        if children:
            _project_tokens(
                children,
                source=source,
                content_root=content_root,
                store=store,
            )
        if token.type == "image":
            label = (token.content or "图片").strip()
            token.type = "text"
            token.tag = ""
            token.nesting = 0
            token.content = f"【{label}仅可在桌面查看】"
            token.attrs = {}
            token.children = None
        elif token.type == "link_open":
            href = _knowledge_href(
                token.attrGet("href") or "",
                source=source,
                content_root=content_root,
                store=store,
            )
            stripped_links.append(href is None)
            if href is None:
                _as_empty_text(token)
            else:
                token.attrSet("href", href)
                if href.startswith(("http://", "https://")):
                    token.attrSet("rel", "noreferrer noopener")
        elif token.type == "link_close":
            stripped = stripped_links.pop() if stripped_links else False
            if stripped:
                _as_empty_text(token)


def render_mobile_markdown(
    markdown: str,
    *,
    source: Path | None,
    content_root: Path,
    store: KnowledgeStore,
) -> str:
    """Render knowledge Markdown without assets, source links, or desktop paths."""

    safe_markdown = DANGEROUS_SCHEME_RE.sub(
        lambda match: f"{match.group(1)}：",
        markdown,
    )
    tokens = MOBILE_MARKDOWN.parse(safe_markdown)
    _project_tokens(
        tokens,
        source=source,
        content_root=content_root,
        store=store,
    )
    rendered = MOBILE_MARKDOWN.renderer.render(tokens, MOBILE_MARKDOWN.options, {})
    private_root = escape(str(content_root.resolve()))
    return rendered.replace(private_root, "本地知识库")
