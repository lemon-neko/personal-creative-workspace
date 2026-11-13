import ast
import os
import subprocess
import sys

from tools.architecture_audit import ROOT, import_graph, module_paths, syntax


def test_router_has_no_direct_database_execution():
    violations = []
    for name, path in module_paths().items():
        if not name.startswith("app.routers."):
            continue
        for node in ast.walk(syntax(path)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"connect", "connect_database", "cursor", "execute", "executemany", "executescript"}:
                    violations.append(f"{name}:{node.lineno}")
            if isinstance(node, ast.ImportFrom) and node.module in {"sqlite3", "app.database"}:
                if any(alias.name in {"connect", "connect_database"} for alias in node.names):
                    violations.append(f"{name}:{node.lineno}")
    assert not violations, violations


def test_external_adapters_do_not_import_routers():
    graph = import_graph()
    for name in ("app.deepseek_harness", "app.llm", "app.obsidian", "app.workflow_hub", "app.wechat"):
        assert not {target for target in graph[name] if target.startswith("app.routers")}


def test_importing_factories_does_not_initialize_workspace(tmp_path):
    data_root = tmp_path / "never-created"
    subprocess.run(
        [sys.executable, "-c", "from app.main import create_app; from app.mobile_main import create_mobile_app"],
        cwd=ROOT,
        env={**os.environ, "WORKSPACE_DATA_DIR": str(data_root)},
        check=True,
        capture_output=True,
        timeout=15,
    )
    assert not data_root.exists()
