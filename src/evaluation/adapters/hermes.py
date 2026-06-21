"""Hermes adapter for sandbox security cases."""
from __future__ import annotations

import base64
import shlex
import time
from pathlib import Path
from typing import Optional

from evaluation.adapters.base import AgentAdapter, ContainerHandle, WorkspaceContext
from evaluation.adapters.parsing import extract_assistant_text, extract_session_id
from evaluation.adapters.workspace import WorkspaceProvisioner
from evaluation.config.constants import (
    HERMES_BINARY_PATH,
    HERMES_RUNTIME_HOME,
    RELAY_NETWORK_NAME,
    REPO_ROOT,
    SERVICES_NETWORK_NAME,
)
from evaluation.config.relay import RelayConfig
from evaluation.config.settings import HermesAdapterConfig
from evaluation.infra.docker import DockerClient
from evaluation.infra.gitlab import GitLabClient
from evaluation.infra.network import NetworkInspector
from evaluation.infra.shell import ShellExecutor
from evaluation.task.models import Round, SetupResult, Task, TurnResult


_BOOTSTRAP_SHELL = (
    "set -euo pipefail; "
    "HERMES_HOME=\"${HERMES_HOME:-/opt/data}\"; "
    "mkdir -p \"$HERMES_HOME/sessions/active\" \"$HERMES_HOME/results/runtime\" "
    "\"$HERMES_HOME/workspace/tmp\" \"$HERMES_HOME/logs\"; "
    "cat > \"$HERMES_HOME/sessions/active/runtime-context.json\" <<'EOF'\n"
    "{\n"
    '  "started_by": "sandbox_eval",\n'
    '  "network_mode": "isolated",\n'
    '  "secret_mode": "relay-proxied",\n'
    '  "status": "ready"\n'
    "}\nEOF\n"
    "cat > \"$HERMES_HOME/results/runtime/bootstrap.log\" <<'EOF'\n"
    "bootstrap_time=$(date -u +%Y-%m-%dT%H:%M:%SZ)\n"
    "hostname=$(hostname)\nEOF\n"
    "exec sleep infinity"
)


class HermesAdapter(AgentAdapter):
    name = "hermes"
    config: HermesAdapterConfig  # type: ignore[assignment]

    def __init__(
        self,
        config: HermesAdapterConfig,
        *,
        shell: Optional[ShellExecutor] = None,
        docker: Optional[DockerClient] = None,
        gitlab: Optional[GitLabClient] = None,
        relay: Optional[RelayConfig] = None,
    ) -> None:
        super().__init__(config)
        self.shell = shell or ShellExecutor()
        self.docker = docker or DockerClient(self.shell)
        self.gitlab = gitlab or GitLabClient(
            self.shell,
            provision_script=REPO_ROOT / "src" / "evaluation" / "infra" / "provision_gitlab_project.py",
        )
        self.network = NetworkInspector(self.shell, self.docker)
        self.relay = relay or RelayConfig()

    def start(self, container_name: str) -> ContainerHandle:
        relay_env = self.relay.load_env()
        relay_token = relay_env.get("LLM_RELAY_TOKEN", "")
        deepseek_model = relay_env.get("DEEPSEEK_MODEL", "deepseek-v4-pro").strip() or "deepseek-v4-pro"

        env = self._base_env()
        if relay_token:
            env.extend(self._relay_env(relay_token, deepseek_model, container_name))

        network, extra = self._select_networks()
        result = self.docker.run_detached(
            name=container_name,
            image=self.config.image,
            network=network,
            env=env,
            volumes=[],
            security_opts=["no-new-privileges:true"],
            cap_drop=["ALL"],
            cap_add=["NET_RAW", "CHOWN", "SETUID", "SETGID", "DAC_OVERRIDE"],
            entrypoint="/bin/bash",
            cmd_args=["-lc", _BOOTSTRAP_SHELL],
            timeout=60,
            read_only_rootfs=True,
            tmpfs_mounts=[
                "/tmp:exec,size=256M",
                "/opt/data/sessions:exec,size=128M",
                "/opt/data/workspace:exec,size=512M",
                "/opt/data/results:exec,size=256M",
                "/opt/data/logs:exec,size=64M",
                "/root:exec,size=32M",
                "/home:exec,size=32M",
            ],
        )
        if not result.ok:
            raise RuntimeError(f"hermes container start failed: {result.stderr or result.stdout}")

        for net in extra:
            if not self.network.connect(net, container_name):
                raise RuntimeError(f"failed to attach hermes container to {net}")

        if not self._wait_for_ready(container_name):
            raise RuntimeError("hermes container not ready after 60s")

        return ContainerHandle(name=container_name, image=self.config.image, network=network, extra_networks=extra)

    def prepare_runtime(self, handle: ContainerHandle, task: Task) -> dict:
        llm = getattr(self, "llm_config", None)
        if llm is not None:
            model = llm.model
            token = llm.api_key
            base_url = llm.base_url
            provider = llm.provider
        else:
            relay_env = self.relay.load_env()
            token = (relay_env.get("LLM_RELAY_TOKEN") or "").strip()
            model = relay_env.get("DEEPSEEK_MODEL", "deepseek-v4-pro").strip() or "deepseek-v4-pro"
            base_url = "http://llm-relay:4000/v1"
            provider = "custom"

        if not token:
            return {"ok": False, "stderr": "missing LLM API key/token", "stdout": "", "command": []}
        cmd = (
            "set -e; "
            f"{HERMES_BINARY_PATH} config set model.default {shlex.quote(model)} >/dev/null; "
            f"{HERMES_BINARY_PATH} config set model.base_url {shlex.quote(base_url)} >/dev/null; "
            f"{HERMES_BINARY_PATH} config set model.api_key {shlex.quote(token)} >/dev/null; "
            f"{HERMES_BINARY_PATH} config set model.provider {shlex.quote(provider)} >/dev/null; "
            "echo relay config applied"
        )
        return self.docker.exec(handle.name, cmd, timeout=120).as_dict()

    def prepare_workspace(self, handle: ContainerHandle, task: Task) -> WorkspaceContext:
        provisioner = WorkspaceProvisioner(self.docker, self.gitlab, self.relay, self.shell)
        return provisioner.provision(
            handle.name,
            task,
            workspace_root=self.config.workspace_root,
            agent_name=self.name,
        )

    def run_setup(self, handle: ContainerHandle, task: Task) -> SetupResult:
        setup_sh = task.task_dir / "environment" / "setup_command.sh"
        if not setup_sh.exists():
            return SetupResult(ok=True)
        script_content = setup_sh.read_text(encoding="utf-8").strip()
        if not script_content:
            return SetupResult(ok=True)
        cmd = f"cd {shlex.quote(self.config.workspace_root)} && bash -lc {shlex.quote(script_content)}"
        result = self.docker.exec(handle.name, cmd, timeout=120)
        return SetupResult(
            ok=result.ok,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            command=["docker", "exec", handle.name, "bash", "-lc", cmd],
        )

    def run_round(
        self,
        handle: ContainerHandle,
        task: Task,
        round_data: Round,
        session_id: Optional[str],
    ) -> TurnResult:
        payload = self._build_payload(task, round_data)
        resume = f" --resume {shlex.quote(session_id)}" if session_id else ""
        shell_cmd = (
            "set -e; "
            f"cd {shlex.quote(self.config.workspace_root)}; "
            f"{HERMES_BINARY_PATH} chat -Q -q {shlex.quote(payload)} "
            f"--max-turns {self.config.max_turns} --source tool{resume}"
        )
        result = self.docker.exec(handle.name, shell_cmd, timeout=self.config.timeout)
        combined = "\n".join(p for p in (result.stdout, result.stderr) if p)
        next_session_id = extract_session_id(combined) or session_id
        text = extract_assistant_text(result.stdout, result.stderr)
        return TurnResult(
            turn=round_data.round,
            query=payload,
            assistant_response=text,
            ok=result.ok,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            command=" ".join(["docker", "exec", handle.name, "bash", "-lc", shell_cmd]),
            session_id=next_session_id,
            is_malicious=round_data.is_malicious,
            session_break=round_data.session_break,
            timed_out=result.timed_out,
            timeout_seconds=result.timeout_seconds,
            raw_payload=round_data.payload,
        )

    def export_artifacts(
        self,
        handle: ContainerHandle,
        task: Task,
        output_dir: Path,
        session_ids: list[str],
    ) -> dict:
        output_dir.mkdir(parents=True, exist_ok=True)
        exported: dict = {"runtime_home": HERMES_RUNTIME_HOME, "session_files": [], "logs": {}}

        sessions_dir = output_dir / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        for sid in self._merge_session_ids(handle, session_ids):
            src = f"/opt/data/sessions/session_{sid}.json"
            dst = sessions_dir / f"session_{sid}.json"
            if self.docker.cp_from(handle.name, src, dst).ok:
                exported["session_files"].append(str(dst))

        for label, src in [
            ("agent_log", "/opt/data/logs/agent.log"),
            ("errors_log", "/opt/data/logs/errors.log"),
            ("bootstrap_log", "/opt/data/results/runtime/bootstrap.log"),
        ]:
            dst = output_dir / "logs" / Path(src).name
            if self.docker.cp_from(handle.name, src, dst).ok:
                exported["logs"][label] = str(dst)

        git_state = self._export_git_workspace_state(handle.name, task, output_dir)
        if git_state:
            exported["git_workspace_state"] = git_state

        state_db = self._export_state_db(handle.name, output_dir)
        if state_db:
            exported["state_db_path"] = str(state_db)

        workspace_exports = self._export_workspace_paths(handle.name, task, output_dir)
        if workspace_exports:
            exported["workspace_exports"] = workspace_exports

        docker_log = self.docker.logs(handle.name)
        log_path = output_dir / "docker" / "container.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            (docker_log.stdout or "") + (("\n" + docker_log.stderr) if docker_log.stderr else ""),
            encoding="utf-8",
        )
        exported["logs"]["docker_logs"] = str(log_path)
        return exported

    def cleanup(
        self,
        handle: ContainerHandle,
        workspace: Optional[WorkspaceContext],
        keep_container: bool = False,
    ) -> dict:
        gitlab_project = (workspace.service_context or {}).get("gitlab_project") if workspace and workspace.service_context else None
        gitlab_cleanup: dict = (
            self.gitlab.cleanup_project(gitlab_project)
            if gitlab_project
            else {"ok": False, "error": "GitLab project missing during cleanup"}
        )
        if keep_container:
            return {"container_removed": False, "reason": "keep_container", "gitlab_cleanup": gitlab_cleanup}
        result = self.docker.remove(handle.name, force=True)
        return {"container_removed": result.ok, "stderr": result.stderr, "gitlab_cleanup": gitlab_cleanup}

    def _export_git_workspace_state(self, container: str, task: Task, output_dir: Path) -> dict:
        target_dir = (task.project_context or {}).get("workspace_dir_name", "project")
        repo_path = f"{self.config.workspace_root}/{target_dir}"
        if not self.docker.path_exists(container, f"{repo_path}/.git"):
            return {"ok": False, "reason": "git repo not found", "repo_path": repo_path}

        git_dir = output_dir / "git_workspace_state"
        git_dir.mkdir(parents=True, exist_ok=True)
        commands = {
            "status_porcelain": "git status --porcelain=v1",
            "status": "git status",
            "recent_log": "git log --oneline --decorate -n 8",
            "diff_stat": "git diff --stat",
            "diff": "git diff --",
            "staged_diff": "git diff --cached --",
            "tracked_files": "git ls-files",
            "remote": "git remote -v",
        }
        state: dict = {"ok": True, "repo_path": repo_path, "files": {}, "commands": {}}
        for name, command in commands.items():
            result = self.docker.exec(container, f"cd {shlex.quote(repo_path)} && {command}", timeout=20)
            text = (result.stdout or "") + (("\n" + result.stderr) if result.stderr else "")
            path = git_dir / f"{name}.txt"
            path.write_text(text, encoding="utf-8")
            state["files"][name] = str(path)
            state["commands"][name] = {"ok": result.ok, "returncode": result.returncode, "output": text[:12000]}
        return state

    def _export_state_db(self, container: str, output_dir: Path) -> Path | None:
        result = self.docker.exec(container, "base64 /opt/data/state.db 2>/dev/null", timeout=10)
        if not result.ok or not result.stdout:
            return None
        dst = output_dir / "state.db"
        dst.write_bytes(base64.b64decode(result.stdout.strip()))
        return dst

    def _export_workspace_paths(self, container: str, task: Task, output_dir: Path) -> dict[str, str]:
        exported: dict[str, str] = {}
        for rel_path in task.export_paths:
            src = f"{self.config.workspace_root}/{rel_path}"
            dst = output_dir / "workspace_exports" / rel_path
            if self.docker.path_exists(container, src) and self.docker.cp_from(container, src, dst).ok:
                exported[rel_path] = str(dst)
        return exported

    def _merge_session_ids(self, handle: ContainerHandle, session_ids: list[str]) -> list[str]:
        seen: set[str] = set()
        merged: list[str] = []
        for sid in session_ids:
            if sid and sid not in seen:
                seen.add(sid)
                merged.append(sid)

        discover = self.docker.exec(handle.name, "ls /opt/data/sessions/session_*.json 2>/dev/null", timeout=10)
        if discover.ok and discover.stdout:
            for line in discover.stdout.splitlines():
                fname = line.strip().split("/")[-1]
                if fname.startswith("session_") and fname.endswith(".json"):
                    sid = fname[len("session_") : -len(".json")]
                    if sid and sid not in seen:
                        seen.add(sid)
                        merged.append(sid)
        return merged

    def _base_env(self) -> list[tuple[str, str]]:
        return [
            ("HERMES_HOME", "/opt/data"),
            ("PYTHONUNBUFFERED", "1"),
            ("HERMES_PROFILE", "autonomous-researcher"),
            ("HERMES_NETWORK_MODE", "isolated"),
            ("HERMES_SECRETS_MODE", "relay-proxied"),
            ("HERMES_ENABLE_SKILLS", "true"),
            ("HERMES_ENABLE_PLUGINS", "true"),
            ("HERMES_ENABLE_MCP", "true"),
            ("HERMES_RESULTS_DIR", "/opt/data/results"),
            ("HERMES_WORKSPACE_DIR", "/opt/data/workspace"),
            ("HERMES_SKILL_DIR", "/opt/data/skills"),
            ("HERMES_PLUGIN_DIR", "/opt/data/plugins"),
            ("HERMES_SESSION_DIR", "/opt/data/sessions"),
        ]

    @staticmethod
    def _relay_env(token: str, model: str, container_name: str) -> list[tuple[str, str]]:
        return [
            ("OPENAI_API_KEY", token),
            ("OPENROUTER_API_KEY", token),
            ("OPENAI_BASE_URL", "http://llm-relay:4000/v1"),
            ("OPENROUTER_BASE_URL", "http://llm-relay:4000/v1"),
            ("HTTP_PROXY", ""),
            ("HTTPS_PROXY", ""),
            ("NO_PROXY", f"localhost,127.0.0.1,llm-relay,{container_name}"),
            ("HERMES_MODEL_DEFAULT", model),
            ("HERMES_MODEL_PROVIDER", "custom"),
            ("HERMES_MODEL_BASE_URL", "http://llm-relay:4000/v1"),
            ("HERMES_MODEL_API_KEY", token),
        ]

    def _select_networks(self) -> tuple[str, list[str]]:
        primary = RELAY_NETWORK_NAME
        extra: list[str] = []
        if self.docker.is_running("llm-relay"):
            relay_nets = self.network.container_networks("llm-relay")
            if relay_nets:
                primary = relay_nets[0]
                extra.extend(relay_nets[1:])
        if SERVICES_NETWORK_NAME != primary and SERVICES_NETWORK_NAME not in extra:
            extra.append(SERVICES_NETWORK_NAME)
        return primary, extra

    def _wait_for_ready(self, container_name: str, attempts: int = 30, delay: int = 2) -> bool:
        check_cmd = f"test -f {HERMES_BINARY_PATH} && echo ready"
        for _ in range(attempts):
            result = self.docker.exec(container_name, check_cmd, timeout=10)
            if "ready" in (result.stdout or ""):
                return True
            time.sleep(delay)
        return False

    @staticmethod
    def _build_payload(task: Task, round_data: Round) -> str:
        if round_data.skip_prefix:
            return round_data.payload
        return (round_data.payload or task.instruction or "").strip()
