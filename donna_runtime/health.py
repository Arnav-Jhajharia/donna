from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class HealthCheck:
    name: str
    ok: bool
    detail: str


def run_health_checks() -> list[HealthCheck]:
    checks = [
        _module_check("claude_agent_sdk", "claude-agent-sdk Python package"),
        _module_check("langsmith", "langsmith Python package"),
        _claude_cli_check(),
        _env_key_check("ANTHROPIC_API_KEY", "Anthropic API key env"),
        _env_key_check("LANGSMITH_API_KEY", "LangSmith API key env", required=False),
        _path_check(Path.cwd(), "current working directory"),
        _path_check(Path.home() / ".claude", "Claude home directory", required=False),
    ]
    return checks


def render_health_report() -> str:
    checks = run_health_checks()
    lines = ["# Donna Health", ""]
    for check in checks:
        marker = "ok" if check.ok else "fail"
        lines.append(f"- [{marker}] {check.name}: {check.detail}")
    failures = [check for check in checks if not check.ok and check.name not in {"LangSmith API key env"}]
    lines.extend(["", f"Required failures: {len(failures)}"])
    return "\n".join(lines)


def _module_check(module_name: str, label: str) -> HealthCheck:
    found = importlib.util.find_spec(module_name) is not None
    return HealthCheck(label, found, "installed" if found else f"missing module {module_name}")


def _claude_cli_check() -> HealthCheck:
    path = shutil.which("claude")
    if not path:
        return HealthCheck("Claude CLI", False, "missing `claude` executable")
    try:
        result = subprocess.run(
            [path, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except OSError as exc:
        return HealthCheck("Claude CLI", False, str(exc))
    version = (result.stdout or result.stderr).strip()
    return HealthCheck("Claude CLI", result.returncode == 0, version or path)


def _env_key_check(name: str, label: str, required: bool = True) -> HealthCheck:
    value = os.getenv(name)
    if value:
        return HealthCheck(label, True, "set")
    return HealthCheck(label, not required, "missing")


def _path_check(path: Path, label: str, required: bool = True) -> HealthCheck:
    if not path.exists():
        return HealthCheck(label, not required, f"missing: {path}")
    writable = os.access(path, os.W_OK)
    detail = f"{path} ({'writable' if writable else 'not writable'})"
    return HealthCheck(label, writable or not required, detail)
