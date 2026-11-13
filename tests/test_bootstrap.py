from __future__ import annotations

import inspect
import os
import stat
import subprocess
import sys
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import Depends, Request
from fastapi.testclient import TestClient

from app.backup import create_encrypted_backup
from app.bootstrap import container as assembly
from app.bootstrap.app_factory import create_workspace_app
from app.bootstrap.config import WorkspaceAppConfig
from app.bootstrap.container import AppContainer, build_container
from app.bootstrap.dependencies import get_container
from app.llm import LLMConfig, OpenAICompatibleClient
from app.main import REPO_ROOT, create_app


@pytest.fixture(autouse=True)
def isolate_model_settings(monkeypatch):
    for name in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "LOCAL_LLM_API_KEY",
                 "LOCAL_LLM_BASE_URL", "LOCAL_LLM_MODEL", "MODEL_ALLOW_EXTERNAL"):
        monkeypatch.delenv(name, raising=False)


def test_build_container_initializes_private_stores_and_seed(tmp_path):
    root = tmp_path / "workspace"
    config = WorkspaceAppConfig(root, root / "content", False, True)

    container = build_container(config)

    assert container.data_root == root
    assert container.content_root == root / "content"
    assert container.model_tasks.usage is container.model_gateway.usage
    assert container.llm_client is container.model_gateway
    assert container.career.learning_paths()
    assert container.plugin_directory == root / "working" / "plugins"
    assert not container.plugins_enabled
    assert container.workflow is None
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    for name in ("workspace.db", "mobile.db"):
        assert stat.S_IMODE((root / name).stat().st_mode) == 0o600


def test_factory_exposes_one_container_with_legacy_aliases(tmp_path):
    application = create_app(data_root=tmp_path, enable_scheduler=False)
    container = application.state.container
    assert isinstance(container, AppContainer)
    for field in fields(AppContainer):
        assert getattr(application.state, field.name) is getattr(container, field.name)
    assert application.state.daily_verified is False
    assert application.state.search_sync_error == ""
    assert application.state.plugins and application.state.primary_nav and application.state.plugin_nav

    replacement = object()
    application.state.career = replacement
    assert container.career is replacement
    container.career = None
    assert application.state.career is None

    @application.get("/_test/container")
    def injected(request: Request, resolved: AppContainer = Depends(get_container)):
        return {"same": resolved is container and resolved is request.app.state.container}

    with TestClient(application, base_url="http://127.0.0.1:8765") as client:
        assert client.get("/_test/container").json() == {"same": True}


@pytest.mark.parametrize("compatible", [False, True])
def test_custom_style_client_is_preserved_and_only_compatible_client_reaches_gateway(tmp_path, compatible):
    stub = (
        OpenAICompatibleClient(LLMConfig("http://127.0.0.1:9999/v1", "", "fixture"))
        if compatible else SimpleNamespace(enabled=False)
    )
    container = create_app(data_root=tmp_path, llm_client=stub, enable_scheduler=False).state.container
    assert container.llm_client is stub
    assert container.model_gateway.client is (stub if compatible else None)


def test_config_keeps_data_root_and_security_defaults(tmp_path, monkeypatch):
    env_root = tmp_path / "from-env"
    vault = tmp_path / "vault"
    explicit = tmp_path / "explicit"
    monkeypatch.setenv("WORKSPACE_DATA_DIR", str(env_root))
    monkeypatch.chdir(tmp_path)
    config = create_app(enable_scheduler=False).state
    assert (config.data_root, config.content_root, config.enforce_security) == (env_root, env_root / "content", True)
    config = create_app(Path("vault"), enable_scheduler=False).state
    assert (config.data_root, config.content_root, config.enforce_security) == (vault, vault, False)
    config = create_app(Path("vault"), data_root=Path("explicit"), enable_scheduler=False).state
    assert (config.data_root, config.content_root, config.enforce_security) == (explicit, vault, True)
    assert create_app(vault, enable_scheduler=False, enforce_security=True).state.enforce_security


def test_default_root_uses_application_support_without_creating_it(tmp_path, monkeypatch):
    monkeypatch.delenv("WORKSPACE_DATA_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    config = WorkspaceAppConfig.resolve(None, data_root=None, enable_scheduler=True, enforce_security=None)
    assert config.data_root == tmp_path / "Library/Application Support/personal-creative-workspace"
    assert not config.data_root.exists()


def test_factory_preserves_signature_and_import_has_no_disk_side_effects(tmp_path):
    assert create_app is create_workspace_app
    parameters = inspect.signature(create_app).parameters
    assert tuple(parameters) == ("content_root", "data_root", "enable_scheduler", "llm_client", "enforce_security")
    assert parameters["content_root"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert all(parameters[name].kind is inspect.Parameter.KEYWORD_ONLY for name in tuple(parameters)[1:])
    assert tuple(parameter.default for parameter in parameters.values()) == (None, None, True, None, None)

    root = tmp_path / "untouched"
    subprocess.run(
        [sys.executable, "-c", "from app.bootstrap.app_factory import create_workspace_app; from app.main import create_app"],
        env={**os.environ, "WORKSPACE_DATA_DIR": str(root)},
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        timeout=15,
    )
    assert not root.exists()


def test_factory_constructs_each_dependency_once_in_legacy_order(tmp_path, monkeypatch):
    names = (
        "prepare_private_root", "initialize_workspace_database", "initialize_mobile_database",
        "ModelGateway", "ModelTaskStore", "CareerRepository", "FocusRepository",
        "VideoProjectRepository", "SearchRepository", "AgentCoreRepository", "AssistantRepository",
        "IncomeRepository", "WechatPublisher", "MobileStore", "ObsidianBridge",
    )
    calls = []

    def track(name, implementation):
        def wrapped(*args, **kwargs):
            calls.append(name)
            return implementation(*args, **kwargs)
        return wrapped

    for name in names:
        monkeypatch.setattr(assembly, name, track(name, getattr(assembly, name)))
    create_app(data_root=tmp_path, enable_scheduler=False)
    assert calls == list(names)


def test_invalid_workflow_config_preserves_enabled_plugin_fallback(tmp_path):
    root = tmp_path / "working" / "plugins"
    root.mkdir(parents=True)
    (root / "enabled").touch()
    (root / "harness.json").write_text("[]", encoding="utf-8")

    application = create_app(data_root=tmp_path, enable_scheduler=False)
    assert application.state.container.plugins_enabled
    assert application.state.workflow is None
    response = TestClient(application, base_url="http://127.0.0.1:8765").get("/tasks")
    assert response.status_code == 503
    assert "执行后端配置无效" in response.text


def test_restore_route_replaces_career_in_state_and_container(tmp_path):
    application = create_app(content_root=tmp_path / "content", data_root=tmp_path,
                             enable_scheduler=False, enforce_security=False)
    container = application.state.container
    previous = container.career
    archive = tmp_path / "working" / "restore-fixture.zip"
    create_encrypted_backup(tmp_path, "synthetic-password", archive)

    with TestClient(application) as client:
        response = client.post("/settings/backups/restore", data={
            "restore_token": archive.name,
            "password": "synthetic-password",
            "confirmation": "恢复备份",
        })
        assert response.status_code == 200
        assert "恢复完成" in response.text

    assert application.state.career is container.career
    assert container.career is not previous
