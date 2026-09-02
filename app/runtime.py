"""Explicit macOS launchd management for the two loopback-only services."""

from __future__ import annotations

import argparse
import os
import plistlib
import pwd
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from app.privacy import default_data_root, prepare_private_root


DESKTOP_LABEL = "com.lemon-neko.personal-creative-workspace.desktop"
MOBILE_LABEL = "com.lemon-neko.personal-creative-workspace.mobile"
MAX_LOG_BYTES = 5 * 1024 * 1024
LAUNCHCTL = "/bin/launchctl"
SAFE_RUNTIME_PATH = "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"


@dataclass(frozen=True)
class ServiceStatus:
    name: str
    label: str
    port: int
    installed: bool
    loaded: bool
    running: bool
    pid: int | None
    port_open: bool
    last_log_at: str


@dataclass(frozen=True)
class TailnetStatus:
    installed: bool
    connected: bool
    serve_enabled: bool
    funnel_enabled: bool
    detail: str


@dataclass(frozen=True)
class DataPermissionStatus:
    root_mode: str
    database_modes: tuple[tuple[str, str], ...]
    healthy: bool


def launch_agents_directory(home: Path | None = None) -> Path:
    return (home or Path.home()) / "Library" / "LaunchAgents"


def service_specs() -> tuple[tuple[str, str, int, str], ...]:
    return (
        ("desktop", DESKTOP_LABEL, 8765, "app"),
        ("mobile", MOBILE_LABEL, 8766, "app.mobile_launcher"),
    )


def agent_path(label: str, *, home: Path | None = None) -> Path:
    return launch_agents_directory(home) / f"{label}.plist"


def build_launch_agent(
    *,
    label: str,
    module: str,
    python: Path,
    repository_root: Path,
    data_root: Path,
) -> dict:
    logs = data_root / "logs"
    # Keep the virtual-environment entry point intact. Resolving this symlink
    # points launchd at the base interpreter, which cannot see dependencies
    # installed in ``.venv`` (for example uvicorn).
    python_executable = Path(os.path.abspath(python))
    username = pwd.getpwuid(os.getuid()).pw_name
    return {
        "Label": label,
        "ProgramArguments": [str(python_executable), "-m", module],
        "WorkingDirectory": str(repository_root),
        "EnvironmentVariables": {
            "WORKSPACE_DATA_DIR": str(data_root),
            # Tailscale's macOS CLI talks to the GUI app through the current
            # user's runtime environment. launchd does not reliably inherit
            # these values from an interactive shell.
            "HOME": str(Path.home()),
            "USER": username,
            "LOGNAME": username,
            "TMPDIR": os.environ.get("TMPDIR", tempfile.gettempdir()),
            "PATH": SAFE_RUNTIME_PATH,
        },
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 15,
        "ProcessType": "Interactive",
        "StandardOutPath": str(logs / f"{label}.log"),
        "StandardErrorPath": str(logs / f"{label}.error.log"),
    }


def _rotate(path: Path) -> None:
    if not path.exists() or path.stat().st_size <= MAX_LOG_BYTES:
        return
    previous = path.with_suffix(path.suffix + ".1")
    previous.unlink(missing_ok=True)
    path.replace(previous)


def _write_agent(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            plistlib.dump(value, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _launchctl(*arguments: str, check: bool = True) -> subprocess.CompletedProcess:
    if not Path(LAUNCHCTL).is_file():
        if check:
            raise RuntimeError("当前系统没有 launchctl；运行管理仅支持 macOS")
        return subprocess.CompletedProcess([LAUNCHCTL, *arguments], 127, "", "")
    return subprocess.run(
        [LAUNCHCTL, *arguments],
        check=check,
        capture_output=True,
        text=True,
        timeout=15,
    )


def _domain() -> str:
    return f"gui/{os.getuid()}"


def install_service(
    name: str,
    *,
    repository_root: Path,
    data_root: Path,
    python: Path | None = None,
) -> Path:
    spec = next((item for item in service_specs() if item[0] == name), None)
    if spec is None:
        raise ValueError(f"未知运行服务：{name}")
    _, label, _, module = spec
    data_root = prepare_private_root(data_root)
    logs = data_root / "logs"
    logs.mkdir(mode=0o700, exist_ok=True)
    logs.chmod(0o700)
    for suffix in (".log", ".error.log"):
        _rotate(logs / f"{label}{suffix}")
    path = agent_path(label)
    value = build_launch_agent(
        label=label,
        module=module,
        python=python or Path(sys.executable),
        repository_root=repository_root.resolve(),
        data_root=data_root.resolve(),
    )
    _write_agent(path, value)
    _launchctl("bootout", _domain(), str(path), check=False)
    _launchctl("bootstrap", _domain(), str(path))
    return path


def uninstall_service(name: str) -> None:
    spec = next((item for item in service_specs() if item[0] == name), None)
    if spec is None:
        raise ValueError(f"未知运行服务：{name}")
    path = agent_path(spec[1])
    _launchctl("bootout", _domain(), str(path), check=False)
    path.unlink(missing_ok=True)


def restart_service(name: str, *, data_root: Path | None = None) -> None:
    spec = next((item for item in service_specs() if item[0] == name), None)
    if spec is None:
        raise ValueError(f"未知运行服务：{name}")
    if data_root is not None:
        logs = data_root / "logs"
        for suffix in (".log", ".error.log"):
            _rotate(logs / f"{spec[1]}{suffix}")
    _launchctl("kickstart", "-k", f"{_domain()}/{spec[1]}")


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.15):
            return True
    except OSError:
        return False


def _last_log_at(data_root: Path | None, label: str) -> str:
    if data_root is None:
        return ""
    candidates = tuple(
        path
        for path in (
            data_root / "logs" / f"{label}.log",
            data_root / "logs" / f"{label}.error.log",
        )
        if path.exists()
    )
    if not candidates:
        return ""
    latest = max(path.stat().st_mtime for path in candidates)
    return datetime.fromtimestamp(latest).astimezone().replace(microsecond=0).isoformat()


def service_statuses(
    *, home: Path | None = None, data_root: Path | None = None
) -> tuple[ServiceStatus, ...]:
    statuses: list[ServiceStatus] = []
    for name, label, port, _module in service_specs():
        path = agent_path(label, home=home)
        completed = _launchctl("print", f"{_domain()}/{label}", check=False)
        loaded = completed.returncode == 0
        match = re.search(r"\bpid\s*=\s*(\d+)", completed.stdout) if loaded else None
        pid = int(match.group(1)) if match else None
        statuses.append(
            ServiceStatus(
                name=name,
                label=label,
                port=port,
                installed=path.is_file(),
                loaded=loaded,
                running=pid is not None,
                pid=pid,
                port_open=_port_open(port),
                last_log_at=_last_log_at(data_root, label),
            )
        )
    return tuple(statuses)


def inspect_tailnet() -> TailnetStatus:
    executable = shutil.which("tailscale")
    if not executable:
        return TailnetStatus(False, False, False, False, "未安装 Tailscale CLI")

    def run(*arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [executable, *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )

    try:
        status = run("status")
        serve = run("serve", "status")
        funnel = run("funnel", "status")
    except (OSError, subprocess.SubprocessError) as error:
        return TailnetStatus(True, False, False, False, str(error))
    serve_text = f"{serve.stdout}\n{serve.stderr}".lower()
    funnel_text = f"{funnel.stdout}\n{funnel.stderr}".lower()
    return TailnetStatus(
        installed=True,
        connected=status.returncode == 0,
        serve_enabled=(
            serve.returncode == 0
            and "https://" in serve_text
            and "127.0.0.1:8766" in serve_text
        ),
        funnel_enabled=funnel.returncode == 0 and "https://" in funnel_text,
        detail="已连接" if status.returncode == 0 else "Tailscale 当前未连接",
    )


def inspect_data_permissions(data_root: Path) -> DataPermissionStatus:
    root_mode = oct(data_root.stat().st_mode & 0o777) if data_root.exists() else "missing"
    database_modes = tuple(
        (path.name, oct(path.stat().st_mode & 0o777))
        for path in (data_root / "workspace.db", data_root / "mobile.db")
        if path.exists()
    )
    healthy = root_mode == "0o700" and all(
        mode == "0o600" for _name, mode in database_modes
    )
    return DataPermissionStatus(root_mode, database_modes, healthy)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="羽白工作台本机运行管理")
    parser.add_argument("action", choices=("install", "status", "restart", "uninstall"))
    parser.add_argument("--mobile", action="store_true", help="同时管理手机网关")
    return parser.parse_args()


def main() -> None:
    arguments = _parse_arguments()
    repository_root = Path(__file__).resolve().parent.parent
    data_root = default_data_root()
    names = ("desktop", "mobile") if arguments.mobile else ("desktop",)
    if arguments.action == "status":
        for status in service_statuses():
            print(asdict(status))
        return
    for name in names:
        if arguments.action == "install":
            path = install_service(
                name,
                repository_root=repository_root,
                data_root=data_root,
            )
            print(f"已安装 {name}: {path}")
        elif arguments.action == "restart":
            restart_service(name, data_root=data_root)
            print(f"已重启 {name}")
        else:
            uninstall_service(name)
            print(f"已卸载 {name}")


if __name__ == "__main__":
    main()
