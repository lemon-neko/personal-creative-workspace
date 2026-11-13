"""Compatibility exports for the desktop workspace."""

from app.bootstrap.app_factory import create_workspace_app as create_app
from app.web import REPO_ROOT


__all__ = ["REPO_ROOT", "create_app"]
