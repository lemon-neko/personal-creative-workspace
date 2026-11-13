from pathlib import Path

from tools.architecture_audit import cyclic_edges, import_graph


def test_scanner_resolves_relative_and_deferred_imports(tmp_path):
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").touch()
    (package / "one.py").write_text("def load():\n    from . import two\n", encoding="utf-8")
    (package / "two.py").write_text("from app.one import load\n", encoding="utf-8")
    graph = import_graph(tmp_path)
    assert graph == {"app": set(), "app.one": {"app.two"}, "app.two": {"app.one"}}
    assert cyclic_edges(graph) == {("app.one", "app.two"), ("app.two", "app.one")}


def test_existing_cycles_cannot_gain_edges():
    baseline = set()
    for line in Path(__file__).with_name("legacy_cycles.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        source, targets = line.split(": ")
        baseline.update((source, target) for target in targets.split(", "))

    actual = cyclic_edges(import_graph())
    assert not (actual - baseline), f"New cyclic import edges: {sorted(actual - baseline)}"
    assert not (baseline - actual), f"Remove resolved edges from the baseline: {sorted(baseline - actual)}"


def test_composition_entries_are_only_imported_by_entrypoints():
    entries = {"app.asgi", "app.mobile_asgi", "app.main", "app.mobile_main", "app.bootstrap.app_factory"}
    allowed = {
        ("app.asgi", "app.main"),
        ("app.mobile_asgi", "app.mobile_main"),
        ("app.main", "app.bootstrap.app_factory"),
    }
    graph = import_graph()
    actual = {(source, target) for source, targets in graph.items() for target in targets & entries}
    assert actual <= allowed


def test_agent_runtime_layers_do_not_depend_on_adapters_or_web():
    graph = import_graph()
    root = "app.agent_runtime."
    for source, targets in graph.items():
        if source.startswith(root + "domain."):
            assert all(target.startswith(root + "domain.") for target in targets), (source, targets)
        if source.startswith((root + "application.", root + "runtime.")):
            assert all(target.startswith((root + "domain.", root + "application.")) for target in targets), (
                source, targets,
            )
