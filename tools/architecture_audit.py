"""List source-level app imports and cycles without importing the application."""

from __future__ import annotations

import argparse
import ast
import json
from importlib.util import resolve_name
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def module_paths(root: Path = ROOT) -> dict[str, Path]:
    modules = {}
    for path in sorted((root / "app").rglob("*.py")):
        parts = path.relative_to(root).with_suffix("").parts
        name = ".".join(parts[:-1] if path.stem == "__init__" else parts)
        modules[name] = path
    return modules


def syntax(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def import_graph(root: Path = ROOT) -> dict[str, set[str]]:
    """Include local, relative and TYPE_CHECKING imports as source dependencies."""

    modules = module_paths(root)
    graph = {name: set() for name in modules}
    for name, path in modules.items():
        package = name if path.stem == "__init__" else name.rpartition(".")[0]
        for node in ast.walk(syntax(path)):
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = resolve_name("." * node.level + (node.module or ""), package)
                children = [f"{base}.{alias.name}" for alias in node.names]
                targets = [child for child in children if child in modules] or [base]
            else:
                continue
            graph[name].update(target for target in targets if target in modules and target != name)
    return graph


def cyclic_edges(graph: dict[str, set[str]]) -> set[tuple[str, str]]:
    """Return each edge that has a return path, including overlapping cycles."""

    def reaches(source: str, target: str) -> bool:
        remaining = [source]
        seen = set()
        while remaining:
            current = remaining.pop()
            if current == target:
                return True
            if current not in seen:
                seen.add(current)
                remaining.extend(graph[current] - seen)
        return False

    return {(source, target) for source, targets in graph.items() for target in targets if reaches(target, source)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()
    graph = import_graph()
    cycles = sorted(cyclic_edges(graph))
    if args.format == "json":
        print(json.dumps({"imports": {name: sorted(targets) for name, targets in graph.items()},
                          "cyclic_edges": cycles}, indent=2))
        return
    print(f"{len(graph)} modules, {sum(map(len, graph.values()))} import edges")
    for name, targets in graph.items():
        print(f"{name}: {', '.join(sorted(targets)) or '—'}")
    for source, target in cycles:
        print(f"cycle: {source} -> {target}")


if __name__ == "__main__":
    main()
