from __future__ import annotations

import asyncio
import sqlite3
from contextlib import AsyncExitStack, asynccontextmanager, suppress

from fastapi import FastAPI

from app.bootstrap.container import AppContainer
from app.content import load_items
from app.knowledge_store import load_knowledge_store
from app.library import load_materials
from app.plugin_runtime import PluginRuntimeManager
from app.workspace import items_directory, run_summary_scheduler


def _sync_search_index(container: AppContainer) -> None:
    root = container.content_root
    container.search.sync(
        items=load_items(items_directory(root)).items,
        knowledge=load_knowledge_store(root),
        materials=load_materials(root),
        career=container.career,
        video=container.video,
    )


async def refresh_search_index(application: FastAPI) -> None:
    try:
        await asyncio.to_thread(_sync_search_index, application.state.container)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        application.state.search_sync_error = str(error)
    else:
        application.state.search_sync_error = ""


@asynccontextmanager
async def workspace_lifespan(application: FastAPI, *, enable_scheduler: bool):
    state = application.state
    container: AppContainer = state.container
    container.agent_core.recover_interrupted_runs()
    try:
        await refresh_search_index(application)
    except sqlite3.Error as error:
        state.search_sync_error = str(error)

    async with AsyncExitStack() as resources:
        scheduler = None
        try:
            if enable_scheduler:
                scheduler = asyncio.create_task(
                    run_summary_scheduler(container.content_root, summarizer=None),
                )
            manager = PluginRuntimeManager(container.plugin_directory, container.workflow)
            state.plugin_runtime = await resources.enter_async_context(
                manager.running(enabled=container.plugins_enabled),
            )
            yield
        finally:
            state.plugin_runtime = None
            if scheduler is not None:
                scheduler.cancel()
                with suppress(asyncio.CancelledError):
                    await scheduler
