from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.privacy import default_data_root


@dataclass(frozen=True)
class WorkspaceAppConfig:
    data_root: Path
    content_root: Path
    enable_scheduler: bool
    enforce_security: bool

    @classmethod
    def resolve(
        cls,
        content_root: Path | None,
        *,
        data_root: Path | None,
        enable_scheduler: bool,
        enforce_security: bool | None,
    ) -> WorkspaceAppConfig:
        content = content_root.resolve() if content_root is not None else None
        test_isolation = content is not None and data_root is None
        if data_root is not None:
            root = data_root.expanduser().resolve()
        else:
            root = content if content is not None else default_data_root().resolve()
        return cls(
            data_root=root,
            content_root=content if content is not None else root / "content",
            enable_scheduler=enable_scheduler,
            enforce_security=not test_isolation if enforce_security is None else enforce_security,
        )
