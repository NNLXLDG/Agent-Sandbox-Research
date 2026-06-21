"""Docker / docker-compose abstraction. All container operations route through here."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from evaluation.infra.shell import CommandResult, ShellExecutor


@dataclass
class ContainerState:
    exists: bool
    running: bool
    status: str


class DockerClient:
    """High-level Docker CLI wrapper.

    Each method is a thin shell around ``docker ...`` subprocess invocation.
    Methods return :class:`CommandResult` so callers can inspect output without
    re-implementing parsing.
    """

    def __init__(self, shell: Optional[ShellExecutor] = None) -> None:
        self.shell = shell or ShellExecutor()

    # ---- container lifecycle -------------------------------------------------

    def state(self, name: str) -> ContainerState:
        result = self.shell.run(
            ["docker", "ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Names}}\t{{.Status}}"],
            timeout=30,
        )
        lines = [line for line in (result.stdout or "").splitlines() if line.strip()]
        if not lines:
            return ContainerState(exists=False, running=False, status="missing")
        _, _, status = lines[0].partition("\t")
        return ContainerState(exists=True, running=status.startswith("Up"), status=status or "unknown")

    def exists(self, name: str) -> bool:
        return self.state(name).exists

    def running(self, name: str) -> bool:
        return self.state(name).running

    def start(self, name: str, timeout: int = 60) -> CommandResult:
        return self.shell.run(["docker", "start", name], timeout=timeout)

    def remove(self, name: str, force: bool = True, timeout: int = 30) -> CommandResult:
        cmd = ["docker", "rm"]
        if force:
            cmd.append("-f")
        cmd.append(name)
        return self.shell.run(cmd, timeout=timeout)

    def run_detached(
        self,
        name: str,
        image: str,
        *,
        network: Optional[str] = None,
        env: Optional[list[tuple[str, str]]] = None,
        volumes: Optional[list[tuple[str, str]]] = None,
        security_opts: Optional[list[str]] = None,
        cap_drop: Optional[list[str]] = None,
        cap_add: Optional[list[str]] = None,
        entrypoint: Optional[str] = None,
        cmd_args: Optional[list[str]] = None,
        extra_args: Optional[list[str]] = None,
        timeout: int = 60,
        read_only_rootfs: bool = False,
        tmpfs_mounts: Optional[list[str]] = None,
    ) -> CommandResult:
        cmd: list[str] = ["docker", "run", "-d", "--name", name]
        if network:
            cmd.extend(["--network", network])
        for key, value in env or []:
            cmd.extend(["-e", f"{key}={value}"])
        for src, dst in volumes or []:
            cmd.extend(["-v", f"{src}:{dst}"])
        for opt in security_opts or []:
            cmd.extend(["--security-opt", opt])
        for cap in cap_drop or []:
            cmd.extend(["--cap-drop", cap])
        for cap in cap_add or []:
            cmd.extend(["--cap-add", cap])
        if read_only_rootfs:
            cmd.append("--read-only")
        for tmpfs_dest in tmpfs_mounts or []:
            cmd.extend(["--tmpfs", tmpfs_dest])
        if entrypoint:
            cmd.extend(["--entrypoint", entrypoint])
        if extra_args:
            cmd.extend(extra_args)
        cmd.append(image)
        if cmd_args:
            cmd.extend(cmd_args)
        return self.shell.run(cmd, timeout=timeout)

    # ---- exec & file ops -----------------------------------------------------

    def exec(self, container: str, shell_cmd: str, timeout: int = 120) -> CommandResult:
        return self.shell.run(
            ["docker", "exec", container, "bash", "-lc", shell_cmd],
            timeout=timeout,
        )

    def exec_argv(self, container: str, argv: list[str], timeout: int = 120) -> CommandResult:
        return self.shell.run(["docker", "exec", container, *argv], timeout=timeout)

    def cp_to(self, container: str, src: Path, dst: str, timeout: int = 60) -> CommandResult:
        return self.shell.run(["docker", "cp", str(src), f"{container}:{dst}"], timeout=timeout)

    def cp_from(self, container: str, src: str, dst: Path, timeout: int = 120) -> CommandResult:
        dst.parent.mkdir(parents=True, exist_ok=True)
        return self.shell.run(["docker", "cp", f"{container}:{src}", str(dst)], timeout=timeout)

    def path_exists(self, container: str, path: str) -> bool:
        return self.shell.run(
            ["docker", "exec", container, "test", "-e", path], timeout=60,
        ).ok

    def logs(self, container: str, timeout: int = 120) -> CommandResult:
        return self.shell.run(["docker", "logs", container], timeout=timeout)

    # ---- inspect helpers -----------------------------------------------------

    def inspect(self, target: str, format_str: str, timeout: int = 30) -> CommandResult:
        return self.shell.run(
            ["docker", "inspect", target, "--format", format_str], timeout=timeout,
        )

    def is_running(self, target: str) -> bool:
        result = self.inspect(target, "{{.State.Running}}")
        return result.ok and "true" in (result.stdout or "").lower()


class ComposeClient:
    """Wraps ``docker compose`` for project lifecycle."""

    def __init__(self, shell: Optional[ShellExecutor] = None) -> None:
        self.shell = shell or ShellExecutor()

    def base_cmd(self, project: str, files: list[Path]) -> list[str]:
        cmd = ["docker", "compose", "-p", project]
        for f in files:
            cmd.extend(["-f", str(f)])
        return cmd

    def up(
        self,
        project: str,
        files: list[Path],
        env: Optional[dict[str, str]] = None,
        cwd: Optional[Path] = None,
        timeout: int = 600,
        build: bool = False,
    ) -> CommandResult:
        cmd = self.base_cmd(project, files) + ["up", "-d"]
        if build:
            cmd.append("--build")
        return self.shell.run(cmd, timeout=timeout, env=env, cwd=cwd)

    def down(
        self,
        project: str,
        files: list[Path],
        env: Optional[dict[str, str]] = None,
        cwd: Optional[Path] = None,
        timeout: int = 600,
        remove_orphans: bool = True,
        volumes: bool = True,
    ) -> CommandResult:
        cmd = self.base_cmd(project, files) + ["down"]
        if remove_orphans:
            cmd.append("--remove-orphans")
        if volumes:
            cmd.append("--volumes")
        return self.shell.run(cmd, timeout=timeout, env=env, cwd=cwd)
