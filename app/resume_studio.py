"""Structured resume models, deterministic matching, and safe tailoring helpers."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Sequence


RESUME_KINDS = {"legacy", "master", "tailored"}
RESUME_TEMPLATE_KEYS = {"ats_single", "china_single_photo"}
RESUME_TEMPLATE_LABELS = {
    "china_single_photo": "技术社招版",
    "ats_single": "ATS 基础版",
}
SECTION_KEYS = (
    "summary",
    "work_experience",
    "education",
    "projects",
    "skills",
    "self_evaluation",
)
SECTION_TITLES = {
    "summary": "职业摘要",
    "work_experience": "工作经历",
    "education": "教育经历",
    "projects": "项目经历",
    "skills": "专业技能",
    "self_evaluation": "自我评价",
}
RESUME_TEMPLATE_SECTION_ORDER = {
    "china_single_photo": (
        "summary",
        "education",
        "skills",
        "work_experience",
        "projects",
        "self_evaluation",
    ),
    # Keep the persisted section order for ATS output. The technical social-hire
    # template deliberately brings skills and evidence forward for fast scanning.
    "ats_single": SECTION_KEYS,
}
PERSONAL_FIELDS = (
    "name",
    "title",
    "email",
    "phone",
    "location",
    "website",
    "github",
    "experience_years",
    "age",
)
MAX_SECTION_ITEMS = 30
MAX_BULLETS = 30


@dataclass(frozen=True)
class ResumeSection:
    key: str
    title: str
    visible: bool
    order: int


@dataclass(frozen=True)
class StructuredResume:
    personal_info: dict[str, str]
    summary: str
    work_experience: tuple[dict[str, Any], ...]
    education: tuple[dict[str, Any], ...]
    projects: tuple[dict[str, Any], ...]
    skills: tuple[str, ...]
    self_evaluation: tuple[str, ...]
    sections: tuple[ResumeSection, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "personal_info": dict(self.personal_info),
            "summary": self.summary,
            "work_experience": [dict(item) for item in self.work_experience],
            "education": [dict(item) for item in self.education],
            "projects": [dict(item) for item in self.projects],
            "skills": list(self.skills),
            "self_evaluation": list(self.self_evaluation),
            "sections": [asdict(section) for section in self.sections],
        }


def display_sections(
    resume: StructuredResume, template_key: str
) -> tuple[ResumeSection, ...]:
    """Return a deterministic display order without rewriting resume data."""

    if template_key not in RESUME_TEMPLATE_KEYS:
        template_key = "ats_single"
    if template_key == "ats_single":
        return tuple(sorted(resume.sections, key=lambda item: item.order))
    priority = {
        key: index
        for index, key in enumerate(RESUME_TEMPLATE_SECTION_ORDER[template_key])
    }
    return tuple(
        sorted(
            resume.sections,
            key=lambda item: (priority.get(item.key, len(priority)), item.order),
        )
    )


_WORK_DATE_RE = re.compile(r"\d{4}(?:[./-]\d{1,2})?")
_WORK_SUBHEADING_RE = re.compile(r"^[^。；;]{1,24}\s+[-–—]\s+[^。；;]{1,60}$")


def _display_years(value: Any) -> str:
    return _text(value, 200).replace("–", "-").replace("—", "-")


def _group_years(positions: Sequence[Mapping[str, Any]]) -> str:
    values = [_display_years(row.get("years")) for row in positions]
    values = [value for value in values if value]
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    dates = [match for value in values for match in _WORK_DATE_RE.findall(value)]
    if not dates:
        return " / ".join(dict.fromkeys(values))
    start = min(dates)
    end = "至今" if any("至今" in value for value in values) else max(dates)
    return start if start == end else f"{start} - {end}"


def _group_work_description(value: Any) -> tuple[list[str], list[dict[str, Any]]]:
    lines = value if isinstance(value, (list, tuple)) else ()
    intro: list[str] = []
    groups: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw in lines:
        line = _text(raw, 2000)
        if not line:
            continue
        if _WORK_SUBHEADING_RE.fullmatch(line):
            current = {
                "title": line.replace("–", "-").replace("—", "-"),
                "bullets": [],
            }
            groups.append(current)
        elif current is None:
            intro.append(line)
        else:
            current["bullets"].append(line)
    return intro, groups


def group_work_experience(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Group same-company positions for a two-level resume projection.

    The source rows stay untouched. Company groups retain first-seen order while
    positions retain their original order, so rendering never rewrites resume data.
    """

    grouped: list[dict[str, Any]] = []
    lookup: dict[str, dict[str, Any]] = {}
    for index, source in enumerate(rows):
        row = dict(source)
        company = _text(row.get("company"), 500)
        key = company.casefold() if company else f"__position_{index}"
        group = lookup.get(key)
        if group is None:
            group = {
                "company": company or "工作经历",
                "location": "",
                "years": "",
                "positions": [],
            }
            lookup[key] = group
            grouped.append(group)
        location = _text(row.get("location"), 500)
        known_locations = group.setdefault("_locations", [])
        if location and location not in known_locations:
            known_locations.append(location)
        row["years"] = _display_years(row.get("years"))
        intro, description_groups = _group_work_description(row.get("description"))
        row["description_intro"] = intro
        row["description_groups"] = description_groups
        group["positions"].append(row)

    for group in grouped:
        group["location"] = " / ".join(group.pop("_locations", []))
        group["years"] = _group_years(group["positions"])
    return tuple(grouped)


@dataclass(frozen=True)
class ResumeSourceFingerprint:
    digest: str
    profile_updated_at: str
    project_ids: tuple[str, ...]


@dataclass(frozen=True)
class ResumeKeywordMatch:
    keyword: str
    matched: bool
    source: str


@dataclass(frozen=True)
class ResumeMatchReport:
    keyword_coverage: float | None
    structure_completeness: float
    keyword_matches: tuple[ResumeKeywordMatch, ...]
    checks: tuple[dict[str, Any], ...]
    recommendations: tuple[str, ...]

    @property
    def matched_keywords(self) -> tuple[str, ...]:
        return tuple(row.keyword for row in self.keyword_matches if row.matched)

    @property
    def missing_keywords(self) -> tuple[str, ...]:
        return tuple(row.keyword for row in self.keyword_matches if not row.matched)


@dataclass(frozen=True)
class ResumeTailoringSuggestion:
    path: str
    before: str
    after: str
    reason: str
    evidence_ids: tuple[str, ...]


def _text(value: Any, maximum: int = 20_000) -> str:
    if value is None:
        return ""
    return str(value).strip()[:maximum]


def _string_list(value: Any, *, limit: int = MAX_BULLETS) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        values = re.split(r"[\n,，;；]+", value)
    elif isinstance(value, (list, tuple)):
        values = value
    else:
        raise ValueError("列表字段格式无效")
    cleaned: list[str] = []
    for item in values:
        candidate = _text(item, 2000)
        if candidate and candidate not in cleaned:
            cleaned.append(candidate)
    if len(cleaned) > limit:
        raise ValueError(f"列表最多包含 {limit} 项")
    return tuple(cleaned)


_PROJECT_TECH_PREFIX_RE = re.compile(
    r"^(?:技术栈|技术选型|核心技术)\s*[:：]\s*(?P<value>.+)$"
)


def project_has_structured_content(project: Mapping[str, Any]) -> bool:
    """Whether a project has author-confirmed three-level resume content."""

    return bool(
        _text(project.get("summary"))
        or _string_list(project.get("tech_stack"), limit=100)
        or _string_list(project.get("responsibilities"))
    )


def project_responsibilities(project: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the active responsibility projection without duplicating legacy text."""

    if project_has_structured_content(project):
        return _string_list(project.get("responsibilities"))
    return _string_list(project.get("description"))


def project_structure_candidates(
    resume: StructuredResume, projects: Sequence[Any]
) -> tuple[dict[str, Any], ...]:
    """Build a conservative, review-only mapping for legacy project descriptions."""

    evidence = {str(project.id): project for project in projects}
    candidates: list[dict[str, Any]] = []
    for source in resume.projects:
        row = dict(source)
        legacy = list(_string_list(row.get("description")))
        is_structured = project_has_structured_content(row)
        linked = evidence.get(_text(row.get("project_id"), 200))
        summary = _text(row.get("summary"), 4000)
        tech_stack = list(_string_list(row.get("tech_stack"), limit=100))
        responsibilities = list(_string_list(row.get("responsibilities")))

        if not is_structured:
            if linked is not None:
                summary = _text(getattr(linked, "summary", ""), 4000)
                tech_stack = list(
                    _string_list(getattr(linked, "technologies", ""), limit=100)
                )
            responsibilities = []
            summary_key = re.sub(r"\s+", "", summary).casefold()
            technology_keys = {
                re.sub(r"\s+", "", item).casefold() for item in tech_stack
            }
            for line in legacy:
                match = _PROJECT_TECH_PREFIX_RE.match(line)
                if match:
                    for item in _string_list(match.group("value"), limit=100):
                        if item not in tech_stack:
                            tech_stack.append(item)
                    continue
                normalized = re.sub(r"\s+", "", line).casefold()
                if summary_key and normalized == summary_key:
                    continue
                if normalized and normalized in technology_keys:
                    continue
                responsibilities.append(line)
            if not responsibilities and linked is not None:
                responsibilities = _nonempty_lines(
                    "\n".join(
                        value
                        for value in (
                            getattr(linked, "actions", ""),
                            getattr(linked, "outcome", ""),
                        )
                        if value
                    ),
                    MAX_BULLETS,
                )

        candidates.append(
            row
            | {
                "summary": summary,
                "tech_stack": tech_stack,
                "responsibilities": responsibilities,
                "legacy_description": legacy,
                "needs_confirmation": not is_structured,
            }
        )
    return tuple(candidates)


def _object_list(
    value: Any,
    *,
    fields: tuple[str, ...],
    list_fields: tuple[str, ...] = (),
) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError("简历区块必须是列表")
    if len(value) > MAX_SECTION_ITEMS:
        raise ValueError(f"每个简历区块最多 {MAX_SECTION_ITEMS} 项")
    result: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            raise ValueError("简历区块条目格式无效")
        item: dict[str, Any] = {}
        for field in fields:
            if field in list_fields:
                item[field] = list(_string_list(raw.get(field)))
            else:
                item[field] = _text(raw.get(field), 4000)
        if any(item[field] for field in fields):
            result.append(item)
    return tuple(result)


def normalize_structured_resume(
    payload: Mapping[str, Any] | StructuredResume,
) -> StructuredResume:
    """Validate and normalize a structured resume without adding facts."""

    if isinstance(payload, StructuredResume):
        return payload
    personal_raw = payload.get("personal_info", {})
    if not isinstance(personal_raw, Mapping):
        raise ValueError("个人信息格式无效")
    personal = {key: _text(personal_raw.get(key), 500) for key in PERSONAL_FIELDS}

    raw_sections = payload.get("sections", ())
    section_lookup: dict[str, ResumeSection] = {}
    if raw_sections:
        if not isinstance(raw_sections, (list, tuple)):
            raise ValueError("简历区块设置无效")
        for raw in raw_sections:
            if not isinstance(raw, Mapping):
                raise ValueError("简历区块设置无效")
            key = _text(raw.get("key"), 80)
            if key not in SECTION_KEYS or key in section_lookup:
                raise ValueError("简历区块键无效或重复")
            try:
                order = int(raw.get("order", len(section_lookup)))
            except (TypeError, ValueError) as error:
                raise ValueError("简历区块顺序无效") from error
            section_lookup[key] = ResumeSection(
                key=key,
                title=_text(raw.get("title"), 80) or SECTION_TITLES[key],
                visible=bool(raw.get("visible", True)),
                order=max(0, min(order, 20)),
            )
    sections = tuple(
        sorted(
            (
                section_lookup.get(
                    key,
                    ResumeSection(key, SECTION_TITLES[key], True, index),
                )
                for index, key in enumerate(SECTION_KEYS)
            ),
            key=lambda item: (item.order, SECTION_KEYS.index(item.key)),
        )
    )
    return StructuredResume(
        personal_info=personal,
        summary=_text(payload.get("summary"), 10_000),
        work_experience=_object_list(
            payload.get("work_experience"),
            fields=("title", "company", "location", "years", "description"),
            list_fields=("description",),
        ),
        education=_object_list(
            payload.get("education"),
            fields=("institution", "degree", "years", "description"),
        ),
        projects=_object_list(
            payload.get("projects"),
            fields=(
                "project_id",
                "name",
                "role",
                "years",
                "github",
                "website",
                "summary",
                "tech_stack",
                "responsibilities",
                "description",
            ),
            list_fields=("tech_stack", "responsibilities", "description"),
        ),
        skills=_string_list(payload.get("skills"), limit=100),
        self_evaluation=_string_list(payload.get("self_evaluation"), limit=MAX_BULLETS),
        sections=sections,
    )


def serialize_structured_resume(resume: StructuredResume) -> str:
    return json.dumps(resume.to_payload(), ensure_ascii=False, separators=(",", ":"))


def deserialize_structured_resume(raw: str) -> StructuredResume:
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError as error:
        raise ValueError("结构化简历数据损坏") from error
    if not isinstance(payload, dict):
        raise ValueError("结构化简历必须是对象")
    return normalize_structured_resume(payload)


def source_fingerprint(
    profile: Any, projects: Sequence[Any]
) -> ResumeSourceFingerprint:
    project_ids = tuple(sorted(str(project.id) for project in projects))
    material = {
        "profile": {
            key: getattr(profile, key, "")
            for key in (
                "target_roles",
                "contact",
                "education",
                "experience",
                "certifications",
                "skills",
                "facts",
                "updated_at",
            )
        },
        "projects": [
            {
                key: getattr(project, key, "")
                for key in (
                    "id",
                    "name",
                    "role",
                    "timeframe",
                    "summary",
                    "technologies",
                    "challenge",
                    "actions",
                    "outcome",
                    "evidence",
                    "updated_at",
                )
            }
            for project in sorted(projects, key=lambda item: str(item.id))
        ],
    }
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return ResumeSourceFingerprint(
        digest=hashlib.sha256(encoded).hexdigest(),
        profile_updated_at=getattr(profile, "updated_at", ""),
        project_ids=project_ids,
    )


def _nonempty_lines(value: str, limit: int = 20) -> list[str]:
    return [line.strip(" -•\t") for line in value.splitlines() if line.strip()][:limit]


def build_import_candidate(
    document_text: str, profile: Any, projects: Sequence[Any]
) -> StructuredResume:
    """Build a conservative local candidate; every field remains author-reviewable."""

    document_lines = _nonempty_lines(document_text, 60)
    contact = _text(getattr(profile, "contact", ""), 4000)
    email_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", contact)
    phone_match = re.search(r"(?<!\d)(?:\+?86[- ]?)?1\d{10}(?!\d)", contact)
    github_match = re.search(r"https?://github\.com/[^\s，,]+", contact, re.I)
    website_match = re.search(r"https?://[^\s，,]+", contact, re.I)
    name = ""
    if document_lines and len(document_lines[0]) <= 40:
        name = document_lines[0]

    work_lines = _nonempty_lines(_text(getattr(profile, "experience", "")), 30)
    education_lines = _nonempty_lines(_text(getattr(profile, "education", "")), 15)
    facts = _nonempty_lines(_text(getattr(profile, "facts", "")), 12)
    skills = _string_list(_text(getattr(profile, "skills", "")), limit=100)

    work_experience: list[dict[str, Any]] = []
    if work_lines:
        work_experience.append(
            {
                "title": "工作经历",
                "company": "",
                "location": "",
                "years": "",
                "description": work_lines,
            }
        )
    education: list[dict[str, Any]] = []
    if education_lines:
        education.append(
            {
                "institution": education_lines[0],
                "degree": "",
                "years": "",
                "description": "\n".join(education_lines[1:]),
            }
        )
    project_rows = []
    for project in projects:
        bullets = _nonempty_lines(
            "\n".join(
                value
                for value in (
                    getattr(project, "summary", ""),
                    getattr(project, "actions", ""),
                    getattr(project, "outcome", ""),
                )
                if value
            ),
            12,
        )
        project_rows.append(
            {
                "project_id": str(project.id),
                "name": _text(project.name, 300),
                "role": _text(getattr(project, "role", ""), 300),
                "years": _text(getattr(project, "timeframe", ""), 300),
                "github": "",
                "website": "",
                "summary": _text(getattr(project, "summary", ""), 4000),
                "tech_stack": list(
                    _string_list(getattr(project, "technologies", ""), limit=100)
                ),
                "responsibilities": _nonempty_lines(
                    "\n".join(
                        value
                        for value in (
                            getattr(project, "actions", ""),
                            getattr(project, "outcome", ""),
                        )
                        if value
                    ),
                    MAX_BULLETS,
                ),
                "description": bullets,
            }
        )
    return normalize_structured_resume(
        {
            "personal_info": {
                "name": name,
                "title": _nonempty_lines(
                    _text(getattr(profile, "target_roles", "")), 1
                )[0]
                if _nonempty_lines(_text(getattr(profile, "target_roles", "")), 1)
                else "",
                "email": email_match.group(0) if email_match else "",
                "phone": phone_match.group(0) if phone_match else "",
                "location": "",
                "website": website_match.group(0) if website_match else "",
                "github": github_match.group(0) if github_match else "",
            },
            "summary": "\n".join(facts),
            "work_experience": work_experience,
            "education": education,
            "projects": project_rows,
            "skills": list(skills),
            "self_evaluation": [],
        }
    )


def resume_plain_text(resume: StructuredResume) -> str:
    parts = [value for value in resume.personal_info.values() if value]
    parts.append(resume.summary)
    for collection in (resume.work_experience, resume.education):
        for item in collection:
            for value in item.values():
                if isinstance(value, list):
                    parts.extend(str(entry) for entry in value)
                elif value:
                    parts.append(str(value))
    for project in resume.projects:
        for key in ("name", "role", "years", "github", "website"):
            if project.get(key):
                parts.append(str(project[key]))
        if project_has_structured_content(project):
            parts.extend(
                value
                for value in (
                    _text(project.get("summary")),
                    *_string_list(project.get("tech_stack"), limit=100),
                    *_string_list(project.get("responsibilities")),
                )
                if value
            )
        else:
            parts.extend(_string_list(project.get("description")))
    parts.extend(resume.skills)
    parts.extend(resume.self_evaluation)
    return "\n".join(part for part in parts if part)


_COMMON_TECH_TERMS = (
    "人工智能",
    "大模型",
    "智能体",
    "向量数据库",
    "混合检索",
    "重排",
    "异步",
    "缓存",
    "消息队列",
    "可观测性",
    "容器化",
    "幂等",
    "限流",
    "熔断",
    "降级",
)
_ENGLISH_STOPWORDS = {
    "and",
    "the",
    "with",
    "for",
    "from",
    "this",
    "that",
    "will",
    "have",
    "years",
    "experience",
    "required",
    "preferred",
    "ability",
    "work",
    "using",
}


def extract_job_keywords(
    jd_text: str,
    confirmed_skills: Iterable[str] = (),
) -> tuple[tuple[str, str], ...]:
    """Extract conservative exact-match terms without claiming semantic ATS parity."""

    found: dict[str, tuple[str, str]] = {}
    for raw in confirmed_skills:
        keyword = _text(raw, 120)
        if keyword:
            found[keyword.casefold()] = (keyword, "已确认技能")
    folded = jd_text.casefold()
    for term in _COMMON_TECH_TERMS:
        if term in jd_text:
            found.setdefault(term, (term, "职位原文"))
    for token in re.findall(r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9+.#/-]{1,30}", jd_text):
        key = token.casefold().strip("./-")
        if len(key) < 2 or key in _ENGLISH_STOPWORDS or key.isdigit():
            continue
        if key in folded:
            found.setdefault(key, (token, "职位原文"))
    return tuple(sorted(found.values(), key=lambda row: row[0].casefold()))


def match_resume(
    resume: StructuredResume,
    jd_text: str,
    confirmed_skills: Iterable[str] = (),
) -> ResumeMatchReport:
    resume_text = resume_plain_text(resume).casefold()
    keywords = extract_job_keywords(jd_text, confirmed_skills)
    matches = tuple(
        ResumeKeywordMatch(keyword, keyword.casefold() in resume_text, source)
        for keyword, source in keywords
    )
    coverage = None
    if matches:
        coverage = round(100 * sum(row.matched for row in matches) / len(matches), 1)

    checks = (
        {
            "key": "contact",
            "label": "联系方式",
            "passed": bool(
                resume.personal_info.get("email") or resume.personal_info.get("phone")
            ),
        },
        {"key": "summary", "label": "职业摘要", "passed": bool(resume.summary)},
        {
            "key": "experience",
            "label": "工作经历",
            "passed": bool(resume.work_experience),
        },
        {"key": "education", "label": "教育经历", "passed": bool(resume.education)},
        {"key": "projects", "label": "项目证据", "passed": bool(resume.projects)},
        {"key": "skills", "label": "技能清单", "passed": bool(resume.skills)},
        {
            "key": "dates",
            "label": "经历时间",
            "passed": all(item.get("years") for item in resume.work_experience)
            if resume.work_experience
            else False,
        },
        {
            "key": "evidence",
            "label": "结果型描述",
            "passed": any(
                re.search(r"\d|提升|降低|完成|上线|交付|节省", bullet)
                for bullet in (
                    *(
                        bullet
                        for item in resume.work_experience
                        for bullet in item.get("description", [])
                    ),
                    *(
                        bullet
                        for item in resume.projects
                        for bullet in project_responsibilities(item)
                    ),
                )
            ),
        },
    )
    completeness = round(
        100 * sum(bool(row["passed"]) for row in checks) / len(checks), 1
    )
    recommendations: list[str] = []
    if not keywords:
        recommendations.append("职位缺少已确认的技能关键词；先在职位页确认技能要求。")
    elif coverage is not None and coverage < 60:
        recommendations.append("优先核对缺失关键词，只补充确有证据的能力。")
    if completeness < 75:
        recommendations.append("先补齐缺失区块与经历时间，再调整措辞。")
    if not any(item.get("project_id") for item in resume.projects):
        recommendations.append("至少关联一个项目证据，避免项目描述成为孤立陈述。")
    return ResumeMatchReport(
        keyword_coverage=coverage,
        structure_completeness=completeness,
        keyword_matches=matches,
        checks=checks,
        recommendations=tuple(recommendations),
    )


_TAILOR_PATH = re.compile(
    r"^(summary|skills\.\d+|work_experience\.\d+\.description\.\d+|"
    r"projects\.\d+\.(?:summary|tech_stack\.\d+|responsibilities\.\d+|description\.\d+))$"
)


def _path_value(payload: dict[str, Any], path: str) -> Any:
    value: Any = payload
    for part in path.split("."):
        if isinstance(value, list):
            if not part.isdigit() or int(part) >= len(value):
                raise ValueError("候选字段路径越界")
            value = value[int(part)]
        elif isinstance(value, dict) and part in value:
            value = value[part]
        else:
            raise ValueError("候选字段路径不存在")
    return value


def validate_tailoring_suggestions(
    raw: Any,
    resume: StructuredResume,
    allowed_evidence_ids: set[str],
) -> tuple[ResumeTailoringSuggestion, ...]:
    if not isinstance(raw, list) or len(raw) > 40:
        raise ValueError("简历定制候选必须为不超过 40 条的列表")
    payload = resume.to_payload()
    result: list[ResumeTailoringSuggestion] = []
    paths: set[str] = set()
    for row in raw:
        if not isinstance(row, Mapping):
            raise ValueError("简历定制候选格式无效")
        path = _text(row.get("path"), 200)
        if not _TAILOR_PATH.fullmatch(path) or path in paths:
            raise ValueError("简历定制候选字段无效或重复")
        before = _text(row.get("before"), 4000)
        after = _text(row.get("after"), 4000)
        reason = _text(row.get("reason"), 1000)
        evidence_ids = _string_list(row.get("evidence_ids"), limit=20)
        if str(_path_value(payload, path)) != before:
            raise ValueError("候选修改前内容与当前简历不一致")
        if (
            not after
            or not evidence_ids
            or not set(evidence_ids) <= allowed_evidence_ids
        ):
            raise ValueError("候选修改缺少有效证据")
        paths.add(path)
        result.append(
            ResumeTailoringSuggestion(path, before, after, reason, evidence_ids)
        )
    return tuple(result)


def apply_tailoring_suggestions(
    resume: StructuredResume,
    suggestions: Sequence[ResumeTailoringSuggestion],
    replacements: Mapping[int, str] | None = None,
) -> StructuredResume:
    payload = resume.to_payload()
    replacements = replacements or {}
    for index, suggestion in enumerate(suggestions):
        value: Any = payload
        parts = suggestion.path.split(".")
        for part in parts[:-1]:
            value = value[int(part)] if isinstance(value, list) else value[part]
        final = parts[-1]
        after = _text(replacements.get(index, suggestion.after), 4000)
        if not after:
            raise ValueError("采用的候选内容不能为空")
        if isinstance(value, list):
            value[int(final)] = after
        else:
            value[final] = after
    return normalize_structured_resume(payload)
