"""Enforce per-module coverage for the private-data critical path."""

from __future__ import annotations

import json
import sys
from pathlib import Path


TARGETS = {
    "app/assistant.py": 80.0,
    "app/backup.py": 80.0,
    "app/database.py": 80.0,
    "app/knowledge_store.py": 80.0,
    "app/mobile.py": 80.0,
    "app/model_gateway.py": 80.0,
    "app/privacy.py": 80.0,
    "app/workspace.py": 80.0,
}


def failures(report: dict) -> tuple[str, ...]:
    files = report.get("files", {})
    problems = []
    for name, minimum in TARGETS.items():
        summary = files.get(name, {}).get("summary", {})
        actual = float(summary.get("percent_covered", 0))
        if actual < minimum:
            problems.append(f"{name}: {actual:.1f}% < {minimum:.0f}%")
    return tuple(problems)


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "coverage.json")
    problems = failures(json.loads(path.read_text(encoding="utf-8")))
    if problems:
        raise SystemExit("高风险模块覆盖率不足：\n" + "\n".join(problems))
    print("coverage guard passed: critical modules are at least 80% covered")


if __name__ == "__main__":
    main()
