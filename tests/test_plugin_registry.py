import hashlib
import json
from dataclasses import replace

import pytest

from app.main import create_app
from app.mobile_main import create_mobile_app
from app.plugins import PLUGINS, validate_registry
from tools.architecture_audit import import_graph


@pytest.mark.parametrize(("mutate", "message"), [
    (lambda specs: specs + (specs[0],), "重复"),
    (lambda specs: (replace(specs[0], version="abc"),) + specs[1:], "版本"),
    (lambda specs: (replace(specs[0], dependencies=("missing",)),) + specs[1:], "依赖无效"),
    (lambda specs: (replace(specs[0], dependencies=("daily",)),) + specs[1:], "循环"),
    (lambda specs: (replace(specs[0], primary=False),) + specs[1:], "主导航"),
])
def test_invalid_catalog_is_rejected(mutate, message):
    with pytest.raises(ValueError, match=message):
        validate_registry(mutate(PLUGINS))


def test_catalog_is_static_and_navigation_resolves(tmp_path):
    validate_registry(PLUGINS)
    assert import_graph()["app.plugins"] == {"app.plugin_paths"}
    app = create_app(data_root=tmp_path)
    assert app.state.plugins == PLUGINS
    assert app.state.primary_nav == (("workspace", "日常工作"), ("tasks", "AI 工作流"))
    assert len(PLUGINS) == 10
    for name, _ in app.state.primary_nav + app.state.plugin_nav:
        assert str(app.url_path_for(name)).startswith("/")


def test_existing_routes_keep_path_name_method_and_order(tmp_path):
    desktop, mobile = create_app(data_root=tmp_path), create_mobile_app(data_root=tmp_path)
    assert len(desktop.routes) == 246
    added, = (route for route in desktop.routes if route.name == "control_plugin_runtime")
    assert added.path == "/settings/runtime/plugins/{plugin_id}/{action}" and added.methods == {"POST"}
    for app, expected in (
        (desktop, "aefb247e57eb29c7f54fb13af438c1b32be1c90743fde7200346a7ad17880217"),
        (mobile, "919212750d3852db633ad9e7d9d3b6bf5c305d471c8d368969fca53917de2075"),
    ):
        rows = [
            [route.path, route.name, sorted(getattr(route, "methods", None) or ())]
            for route in app.routes if route is not added
        ]
        assert hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest() == expected
