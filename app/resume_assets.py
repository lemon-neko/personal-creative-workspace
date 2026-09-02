"""Validation helpers for private resume portraits."""

from __future__ import annotations

import base64
import struct
from dataclasses import dataclass


MAX_RESUME_PHOTO_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class ResumeImage:
    content: bytes
    media_type: str
    extension: str
    width: int
    height: int

    @property
    def data_url(self) -> str:
        encoded = base64.b64encode(self.content).decode("ascii")
        return f"data:{self.media_type};base64,{encoded}"


def _png_dimensions(content: bytes) -> tuple[int, int]:
    if len(content) < 24 or not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("PNG 图片签名无效")
    return struct.unpack(">II", content[16:24])


def _jpeg_dimensions(content: bytes) -> tuple[int, int]:
    if len(content) < 4 or not content.startswith(b"\xff\xd8\xff"):
        raise ValueError("JPEG 图片签名无效")
    offset = 2
    while offset + 4 <= len(content):
        if content[offset] != 0xFF:
            offset += 1
            continue
        marker = content[offset + 1]
        offset += 2
        if marker in {0xD8, 0xD9}:
            continue
        if offset + 2 > len(content):
            break
        length = int.from_bytes(content[offset : offset + 2], "big")
        if length < 2 or offset + length > len(content):
            break
        if marker in {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }:
            if length < 7:
                break
            height = int.from_bytes(content[offset + 3 : offset + 5], "big")
            width = int.from_bytes(content[offset + 5 : offset + 7], "big")
            return width, height
        offset += length
    raise ValueError("无法读取 JPEG 尺寸")


def validate_resume_image(content: bytes) -> ResumeImage:
    """Validate a PNG/JPEG portrait by signature and dimensions."""

    if not content or len(content) > MAX_RESUME_PHOTO_BYTES:
        raise ValueError("简历照片不能为空且不能超过 5 MB")
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        width, height = _png_dimensions(content)
        media_type, extension = "image/png", ".png"
    elif content.startswith(b"\xff\xd8\xff"):
        width, height = _jpeg_dimensions(content)
        media_type, extension = "image/jpeg", ".jpg"
    else:
        raise ValueError("简历照片仅支持 PNG 或 JPEG")
    if width < 80 or height < 100 or width > 8000 or height > 8000:
        raise ValueError("简历照片尺寸无效")
    return ResumeImage(content, media_type, extension, width, height)
