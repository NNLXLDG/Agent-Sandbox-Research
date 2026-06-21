"""Unified shell execution. Replaces V1's duplicated ``_run`` and ``run_cmd``."""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class CommandResult:
    """Structured result of a subprocess invocation."""

    ok: bool
    returncode: Optional[int]
    stdout: str
    stderr: str
    command: list[str]
    timed_out: bool = False
    timeout_seconds: Optional[int] = None
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        """Render as a JSON-friendly dict (used by reporters)."""
        out = {
            "ok": self.ok,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "command": self.command,
        }
        if self.timed_out:
            out["timed_out"] = True
            out["timeout_seconds"] = self.timeout_seconds
        out.update(self.extra)
        return out


class ShellExecutor:
    """Thin, mockable wrapper over ``subprocess.run``.

    All other infra components depend on this rather than calling subprocess
    directly, so tests can swap in a fake executor.
    """

    def __init__(self, default_timeout: int = 120) -> None:
        self.default_timeout = default_timeout

    def run(
        self,
        cmd: list[str],
        timeout: Optional[int] = None,
        cwd: Optional[Path] = None,
        env: Optional[dict[str, str]] = None,
        capture: bool = True,
    ) -> CommandResult:
        timeout = timeout or self.default_timeout
        run_env = None if env is None else os.environ.copy() | env
        # On Windows with Git Bash/MSYS, prevent path mangling of Linux paths
        # like /bin/bash → D:/Tools/Git/usr/bin/bash
        if os.name == "nt":
            run_env = run_env or os.environ.copy()
            run_env["MSYS_NO_PATHCONV"] = "1"
            run_env["MSYS2_ARG_CONV_EXCL"] = "*"
        try:
            proc = subprocess.run(
                cmd,
                capture_output=capture,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                cwd=str(cwd) if cwd else None,
                env=run_env,
            )
            return CommandResult(
                ok=proc.returncode == 0,
                returncode=proc.returncode,
                stdout=(proc.stdout or "").strip() if capture else "",
                stderr=(proc.stderr or "").strip() if capture else "",
                command=list(cmd),
            )
        except FileNotFoundError:
            return CommandResult(
                ok=False, returncode=None, stdout="", stderr="command not found",
                command=list(cmd),
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            return CommandResult(
                ok=False,
                returncode=None,
                stdout=stdout,
                stderr=stderr or f"timeout after {timeout}s",
                command=list(cmd),
                timed_out=True,
                timeout_seconds=timeout,
            )

    @staticmethod
    def host_shell() -> list[str]:
        """Return the platform-appropriate shell-prefix for ad-hoc commands."""
        if os.name == "nt":
            powershell = shutil.which("pwsh") or shutil.which("powershell")
            if powershell:
                return [powershell, "-NoProfile", "-Command"]
            return ["cmd", "/C"]
        return ["bash", "-lc"]
