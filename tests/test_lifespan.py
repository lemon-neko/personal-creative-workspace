from __future__ import annotations

import asyncio
import sqlite3
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import lifespan
from app.llm import LLMConfig, OpenAICompatibleClient
from app.main import create_app


@pytest.fixture
def application(tmp_path):
    stub = OpenAICompatibleClient(LLMConfig("http://127.0.0.1:9999/v1", "", "fixture"))
    return create_app(content_root=tmp_path, llm_client=stub)


def test_lifespan_starts_and_drains_resources_in_order(application, monkeypatch):
    state = application.state
    state.plugins_enabled = True
    state.workflow = object()
    events = []
    scheduler_tasks = []

    monkeypatch.setattr(state.agent_core, "recover_interrupted_runs", lambda: events.append("recover"))

    def sync(**sources):
        assert sources["career"] is state.career
        assert sources["video"] is state.video
        events.append("search")

    monkeypatch.setattr(state.search, "sync", sync)

    async def scheduler(root, *, summarizer):
        assert root == state.content_root and summarizer is None
        scheduler_tasks.append(asyncio.current_task())
        events.append("scheduler start")
        try:
            await asyncio.Future()
        finally:
            events.append("scheduler stop")

    @asynccontextmanager
    async def plugins(*, enabled):
        assert enabled
        await asyncio.sleep(0)
        events.append("plugins start")
        try:
            yield SimpleNamespace(daily_ready=True)
        finally:
            assert state.daily_verified is False
            assert scheduler_tasks[0].cancelled()
            events.append("plugins stop")

    monkeypatch.setattr(lifespan, "run_summary_scheduler", scheduler)
    def manager(root, workflow):
        assert root == state.container.plugin_directory
        assert workflow is state.workflow
        return SimpleNamespace(running=plugins)

    monkeypatch.setattr(lifespan, "PluginRuntimeManager", manager)
    with TestClient(application):
        assert state.daily_verified is True
        assert events == ["recover", "search", "scheduler start", "plugins start"]
    assert events == ["recover", "search", "scheduler start", "plugins start", "scheduler stop", "plugins stop"]
    assert state.daily_verified is False


@pytest.mark.parametrize("failure", [OSError, sqlite3.OperationalError])
def test_search_failure_is_reported_and_next_success_clears_it(application, monkeypatch, failure):
    state = application.state

    def fail(**_sources):
        raise failure("synthetic search failure")

    sync = state.search.sync
    monkeypatch.setattr(state.search, "sync", fail)
    with TestClient(application) as client:
        assert client.get("/career").status_code == 200
        assert state.search_sync_error == "synthetic search failure"
        monkeypatch.setattr(state.search, "sync", sync)
        response = client.post("/models/pricing", data={"input_price": 1, "output_price": 2}, follow_redirects=False)
        assert response.status_code == 303
        assert state.search_sync_error == ""


def test_agent_recovery_failure_still_aborts_startup(application, monkeypatch):
    def fail():
        raise RuntimeError("synthetic recovery failure")

    def unexpected(*_args, **_kwargs):
        pytest.fail("startup continued after Agent recovery failed")

    monkeypatch.setattr(application.state.agent_core, "recover_interrupted_runs", fail)
    monkeypatch.setattr(lifespan, "refresh_search_index", unexpected)
    monkeypatch.setattr(lifespan, "PluginRuntimeManager", unexpected)
    monkeypatch.setattr(lifespan, "run_summary_scheduler", unexpected)
    with pytest.raises(RuntimeError, match="synthetic recovery failure"):
        with TestClient(application):
            pytest.fail("startup failure was swallowed")
    assert application.state.daily_verified is False


def test_partial_plugin_startup_failure_releases_plugins_and_awaits_scheduler(application, monkeypatch):
    tasks = []
    released = []

    async def scheduler(*_args, **_kwargs):
        tasks.append(asyncio.current_task())
        try:
            await asyncio.Future()
        finally:
            await asyncio.sleep(0)
            released.append("scheduler")

    @asynccontextmanager
    async def first_plugin():
        try:
            yield
        finally:
            released.append("plugin")

    @asynccontextmanager
    async def plugins(*, enabled):
        async with first_plugin():
            await asyncio.sleep(0)
            raise OSError("synthetic plugin startup failure")
        yield False

    monkeypatch.setattr(lifespan, "run_summary_scheduler", scheduler)
    monkeypatch.setattr(lifespan, "PluginRuntimeManager", lambda *_: SimpleNamespace(running=plugins))
    with pytest.raises(OSError, match="synthetic plugin startup failure"):
        with TestClient(application):
            pytest.fail("startup failure was swallowed")

    assert released == ["plugin", "scheduler"]
    assert len(tasks) == 1 and tasks[0].cancelled()
    assert application.state.daily_verified is False


def test_scheduler_can_be_disabled(tmp_path, monkeypatch):
    def unexpected(*_args, **_kwargs):
        pytest.fail("disabled scheduler was started")

    monkeypatch.setattr(lifespan, "run_summary_scheduler", unexpected)
    with TestClient(create_app(content_root=tmp_path, enable_scheduler=False)):
        pass
