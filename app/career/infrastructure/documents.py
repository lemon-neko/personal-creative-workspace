import io
import mimetypes
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from app.career.domain.profile import (
    ALLOWED_EXTENSIONS,
    MAX_DOCUMENT_BYTES,
    MAX_DOCX_EXPANDED_BYTES,
)


def validate_document(filename: str, content: bytes) -> tuple[str, str, str]:
    """Validate an upload by extension and signature; return extracted local text."""

    if not content or len(content) > MAX_DOCUMENT_BYTES:
        raise ValueError("文件不能为空且不能超过 20 MB")
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("仅支持 PDF、DOCX、Markdown、TXT、PNG 和 JPEG")

    media_type = mimetypes.types_map.get(extension, "application/octet-stream")
    extracted = ""
    if extension == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise ValueError("PDF 文件签名无效")
        media_type = "application/pdf"
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(content))
            if len(reader.pages) > 200:
                raise ValueError("PDF 页数不能超过 200 页")
            extracted = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError:
            extracted = ""
        except Exception as error:
            raise ValueError("PDF 无法安全解析") from error
    elif extension == ".docx":
        if not content.startswith(b"PK"):
            raise ValueError("DOCX 文件签名无效")
        media_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if (
                    sum(item.file_size for item in archive.infolist())
                    > MAX_DOCX_EXPANDED_BYTES
                ):
                    raise ValueError("DOCX 解压后体积过大")
                names = set(archive.namelist())
                if "word/document.xml" not in names or any(
                    name.endswith("vbaProject.bin") for name in names
                ):
                    raise ValueError("DOCX 结构无效或包含宏")
                root = ElementTree.fromstring(archive.read("word/document.xml"))
                extracted = " ".join(text for text in root.itertext() if text.strip())
        except (zipfile.BadZipFile, ElementTree.ParseError) as error:
            raise ValueError("DOCX 无法安全解析") from error
    elif extension in {".md", ".txt"}:
        try:
            extracted = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("文本文件必须使用 UTF-8 编码") from error
        media_type = "text/markdown" if extension == ".md" else "text/plain"
    elif extension == ".png":
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("PNG 文件签名无效")
        media_type = "image/png"
    else:
        if not content.startswith(b"\xff\xd8\xff"):
            raise ValueError("JPEG 文件签名无效")
        media_type = "image/jpeg"
    return extension, media_type, extracted
