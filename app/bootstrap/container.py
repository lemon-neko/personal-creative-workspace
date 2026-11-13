from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.agent_core import AgentCoreRepository
from app.agent_runtime.infrastructure.adapters.model_adapter import ModelAdapter
from app.agent_runtime.infrastructure.adapters.search_adapter import SearchAdapter
from app.assistant import AssistantRepository
from app.bootstrap.config import WorkspaceAppConfig
from app.career import CareerRepository
from app.database import initialize_mobile_database, initialize_workspace_database
from app.focus import FocusRepository
from app.income import IncomeRepository
from app.llm import OpenAICompatibleClient, StyleClient
from app.mobile import MobileStore
from app.model_gateway import ModelGateway, ModelTaskStore
from app.obsidian import ObsidianBridge
from app.plugin_paths import plugin_root
from app.privacy import prepare_private_root
from app.search import SearchRepository
from app.video import VideoProjectRepository
from app.wechat import WechatPublisher
from app.workflow import Workflow, WorkflowConfigurationError


@dataclass
class AppContainer:
    data_root: Path
    content_root: Path
    model_gateway: ModelGateway
    llm_client: StyleClient
    model_tasks: ModelTaskStore
    career: CareerRepository
    focus: FocusRepository
    video: VideoProjectRepository
    search: SearchRepository
    agent_core: AgentCoreRepository
    assistant: AssistantRepository
    income: IncomeRepository
    wechat: WechatPublisher
    mobile_store: MobileStore
    obsidian: ObsidianBridge
    workflow: Workflow | None
    plugin_directory: Path
    plugins_enabled: bool


def build_container(
    config: WorkspaceAppConfig,
    *,
    llm_client: StyleClient | None = None,
) -> AppContainer:
    root = config.data_root
    prepare_private_root(root)
    initialize_workspace_database(root)
    initialize_mobile_database(root)

    gateway = ModelGateway(
        root, client=llm_client if isinstance(llm_client, OpenAICompatibleClient) else None,
    )
    model_tasks = ModelTaskStore(root, gateway.usage)
    career = CareerRepository(root)
    focus = FocusRepository(root)
    video = VideoProjectRepository(root, config.content_root)
    search = SearchRepository(root)
    agent_core = AgentCoreRepository(root, search=SearchAdapter(search), model=ModelAdapter(gateway))
    assistant = AssistantRepository(root)
    income = IncomeRepository(root)
    wechat = WechatPublisher(root, config.content_root)
    mobile_store = MobileStore(root)
    obsidian = ObsidianBridge(root, config.content_root)
    career.seed_career_radar()

    plugin_directory = plugin_root(root)
    plugins_enabled = (plugin_directory / "enabled").is_file()
    workflow = None
    if plugins_enabled:
        try:
            workflow = Workflow(root, gateway)
        except WorkflowConfigurationError:
            pass

    return AppContainer(
        data_root=root,
        content_root=config.content_root,
        model_gateway=gateway,
        llm_client=gateway if llm_client is None else llm_client,
        model_tasks=model_tasks,
        career=career,
        focus=focus,
        video=video,
        search=search,
        agent_core=agent_core,
        assistant=assistant,
        income=income,
        wechat=wechat,
        mobile_store=mobile_store,
        obsidian=obsidian,
        workflow=workflow,
        plugin_directory=plugin_directory,
        plugins_enabled=plugins_enabled,
    )
