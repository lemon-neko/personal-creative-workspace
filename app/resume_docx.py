"""Deterministic local DOCX resume parsing with portrait extraction."""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from typing import Any, Sequence
from xml.etree import ElementTree

from app.resume_assets import ResumeImage, validate_resume_image
from app.resume_studio import StructuredResume, normalize_structured_resume


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
SECTION_NAMES = ("个人概要", "教育背景", "工作经历", "项目经历", "自我评价")
SECTION_SET = set(SECTION_NAMES)
LABELS = {"项目介绍", "技术栈", "个人职责", "项目亮点"}
DATE_RANGE = re.compile(
    r"(?P<years>20\d{2}[./-]\d{1,2}\s*[–—-]\s*(?:20\d{2}[./-]\d{1,2}|至今))"
)


@dataclass(frozen=True)
class DocxResumeCandidate:
    resume: StructuredResume
    portrait: ResumeImage | None
    diagnostics: tuple[str, ...]


def _clean_line(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" \t\r\n•")
    for heading in SECTION_NAMES:
        if value == heading * 2:
            return heading
    return value


def _leaf_paragraphs(root: ElementTree.Element) -> list[str]:
    namespace = {"w": W_NS}
    lines: list[str] = []
    for paragraph in root.findall(".//w:p", namespace):
        if paragraph.findall(".//w:p", namespace):
            continue
        text = "".join(
            node.text or "" for node in paragraph.findall(".//w:t", namespace)
        )
        clean = _clean_line(text)
        if clean and (not lines or clean != lines[-1]):
            lines.append(clean)
    return lines


def _section_ranges(lines: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    positions: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        if line in SECTION_SET and (not positions or positions[-1][1] != line):
            positions.append((index, line))
    first = positions[0][0] if positions else len(lines)
    sections: dict[str, list[str]] = {name: [] for name in SECTION_NAMES}
    for offset, (start, name) in enumerate(positions):
        end = positions[offset + 1][0] if offset + 1 < len(positions) else len(lines)
        sections[name] = [line for line in lines[start + 1 : end] if line != name]
    return lines[:first], sections


def _header_info(lines: list[str], profile: Any) -> dict[str, str]:
    text = " ".join(dict.fromkeys(lines))
    email = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
    phone = re.search(r"(?<!\d)(?:\+?86[- ]?)?1\d{10}(?!\d)", text)
    experience = re.search(r"(\d{1,2})\s*年经验", text)
    age = re.search(r"(\d{1,2})\s*岁", text)
    role = re.search(
        r"(?:AI\s*[-–—]?\s*)?Agent\s*应用开发工程师|"
        r"AI\s*[-–—]?\s*Agent应用开发工程师",
        text,
        re.I,
    )
    name = ""
    for line in lines:
        match = re.fullmatch(r"[\u4e00-\u9fff]{2,5}", line)
        if match:
            name = match.group(0)
            break
    profile_roles = [
        row.strip() for row in str(getattr(profile, "target_roles", "")).splitlines()
        if row.strip()
    ]
    return {
        "name": name,
        "title": role.group(0).replace(" ", "") if role else (profile_roles[0] if profile_roles else ""),
        "email": email.group(0) if email else "",
        "phone": phone.group(0) if phone else "",
        "experience_years": f"{experience.group(1)}年" if experience else "",
        "age": age.group(1) if age else "",
        "location": "",
        "website": "",
        "github": "",
    }


def _education(lines: list[str]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for line in lines:
        date = DATE_RANGE.search(line)
        years = date.group("years") if date else ""
        body = line[: date.start()].strip() if date else line
        degree_match = re.search(r"[（(](本科|硕士|博士|专科)[）)]", body)
        if degree_match:
            before = body[: degree_match.start()].strip()
            parts = before.split(maxsplit=1)
            institution = parts[0] if parts else ""
            major = parts[1] if len(parts) > 1 else ""
            degree = f"{major} · {degree_match.group(1)}" if major else degree_match.group(1)
        else:
            parts = [part.strip() for part in re.split(r"\s{2,}", body) if part.strip()]
            institution = parts[0] if parts else body
            degree = " · ".join(parts[1:])
        if institution:
            result.append(
                {
                    "institution": institution,
                    "degree": degree,
                    "years": years,
                    "description": "",
                }
            )
    return result


def _split_company_title(value: str) -> tuple[str, str]:
    patterns = (
        r"AI\s*算法\+测试开发工程师",
        r"软件开发工程师",
        r"测试开发工程师",
        r"算法工程师",
        r"开发工程师",
        r"工程师",
    )
    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            return value[: match.start()].strip(), match.group(0).strip()
    return value.strip(), ""


def _work_experience(lines: list[str]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in lines:
        date = DATE_RANGE.search(line)
        if date and date.end() == len(line):
            company, title = _split_company_title(line[: date.start()].strip())
            current = {
                "title": title,
                "company": company,
                "location": "",
                "years": date.group("years"),
                "description": [],
            }
            entries.append(current)
            continue
        if current is not None:
            current["description"].append(line)
    return entries


def _normalized_name(value: str) -> str:
    value = re.sub(r"[（(].*?[）)]", "", value)
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.casefold())


def _match_project(name: str, projects: Sequence[Any]) -> Any | None:
    target = _normalized_name(name)
    best = None
    best_length = 0
    for project in projects:
        candidate = _normalized_name(str(project.name))
        if candidate and (candidate in target or target in candidate):
            score = min(len(candidate), len(target))
            if score > best_length:
                best, best_length = project, score
    return best


def _project_rows(lines: list[str], projects: Sequence[Any]) -> tuple[list[dict[str, Any]], bool]:
    starts: list[int] = []
    matches: list[Any] = []
    for index, line in enumerate(lines):
        project = _match_project(line, projects)
        if project is not None and line not in LABELS:
            if not starts or index > starts[-1]:
                starts.append(index)
                matches.append(project)
    rows: list[dict[str, Any]] = []
    previous_details: list[str] = []
    duplicate_removed = False
    for offset, start in enumerate(starts):
        end = starts[offset + 1] if offset + 1 < len(starts) else len(lines)
        raw_details = [line for line in lines[start + 1 : end] if line not in LABELS]
        details = list(raw_details)
        if previous_details and details[: len(previous_details)] == previous_details:
            details = details[len(previous_details) :]
            duplicate_removed = True
        project = matches[offset]
        rows.append(
            {
                "project_id": str(project.id),
                "name": lines[start],
                "role": str(getattr(project, "role", "")),
                "years": str(getattr(project, "timeframe", "")),
                "github": "",
                "website": "",
                "description": details,
            }
        )
        if raw_details:
            previous_details = raw_details
    return rows, duplicate_removed


TECH_TERMS = (
    "Python",
    "C++",
    "Qt",
    "MySQL",
    "PyTorch",
    "BF16",
    "INT8",
    "perf",
    "FunASR",
    "ARM",
    "LLM Agent",
    "RAG",
    "向量数据库",
    "Embedding",
    "MCP",
    "mmengine",
    "TRT-LLM",
    "Torch",
    "ONNX",
    "K8s",
    "CI/CD",
    "JUnit XML",
)


def _skills(text: str, profile: Any) -> list[str]:
    result: list[str] = []

    def key(value: str) -> str:
        value = re.sub(r"\s+[vV]?\d+(?:\.\d+)*$", "", value.strip())
        value = value.replace("++", "plusplus").replace("#", "sharp")
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.casefold())

    def add(value: str) -> None:
        candidate = value.strip()
        candidate_key = key(candidate)
        if not candidate or not candidate_key:
            return
        replace_indices: list[int] = []
        for index, existing in enumerate(result):
            existing_key = key(existing)
            if candidate_key == existing_key:
                replace_indices.append(index)
                continue
            if len(candidate_key) >= 3 and candidate_key in existing_key:
                return
            if len(existing_key) >= 3 and existing_key in candidate_key:
                replace_indices.append(index)
        if replace_indices:
            first = replace_indices[0]
            if len(candidate) >= len(result[first]):
                result[first] = candidate
            for index in reversed(replace_indices[1:]):
                result.pop(index)
            return
        result.append(candidate)

    folded = text.casefold()
    for term in TECH_TERMS:
        if term.casefold() in folded:
            add(term)
    for line in re.split(r"[\n,，、;；]+", str(getattr(profile, "skills", ""))):
        add(line)
    return result[:100]


def _portrait_from_archive(archive: zipfile.ZipFile) -> tuple[ResumeImage | None, int]:
    candidates: dict[str, ResumeImage] = {}
    for name in archive.namelist():
        if not name.startswith("word/media/"):
            continue
        content = archive.read(name)
        try:
            image = validate_resume_image(content)
        except ValueError:
            continue
        ratio = image.width / image.height
        if image.width < 120 or image.height < 160 or not 0.55 <= ratio <= 0.9:
            continue
        candidates.setdefault(hashlib.sha256(content).hexdigest(), image)
    ranked = sorted(candidates.values(), key=lambda item: item.width * item.height, reverse=True)
    return (ranked[0] if ranked else None), len(ranked)


def parse_resume_docx(
    content: bytes,
    profile: Any,
    projects: Sequence[Any],
) -> DocxResumeCandidate:
    """Parse a trusted local DOCX into a reviewable, deterministic candidate."""

    diagnostics: list[str] = []
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = set(archive.namelist())
            if "word/document.xml" not in names or any(
                name.endswith("vbaProject.bin") for name in names
            ):
                raise ValueError("DOCX 结构无效或包含宏")
            root = ElementTree.fromstring(archive.read("word/document.xml"))
            portrait, portrait_count = _portrait_from_archive(archive)
    except (zipfile.BadZipFile, ElementTree.ParseError) as error:
        raise ValueError("DOCX 无法安全解析") from error

    lines = _leaf_paragraphs(root)
    header, sections = _section_ranges(lines)
    missing = [name for name in SECTION_NAMES if not sections[name]]
    if missing:
        diagnostics.append("部分标准区块未识别，请在确认前检查")
    projects_rows, duplicate_removed = _project_rows(
        sections["项目经历"], projects
    )
    if duplicate_removed:
        diagnostics.append("已跳过后续项目中与上一项目完全重复的介绍段落")
    if portrait is not None:
        diagnostics.append("已识别并去重证件照")
    if portrait_count > 1:
        diagnostics.append("检测到多张不同的候选照片，默认使用尺寸最大的一张")

    resume = normalize_structured_resume(
        {
            "personal_info": _header_info(header, profile),
            "summary": "\n".join(sections["个人概要"]),
            "work_experience": _work_experience(sections["工作经历"]),
            "education": _education(sections["教育背景"]),
            "projects": projects_rows,
            "skills": _skills("\n".join(lines), profile),
            "self_evaluation": sections["自我评价"],
        }
    )
    return DocxResumeCandidate(resume, portrait, tuple(diagnostics))
