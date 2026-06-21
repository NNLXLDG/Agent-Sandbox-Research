"""OpenClaw adapter for sandbox security cases."""
from __future__ import annotations

import json
import shlex
import uuid
from pathlib import Path
from typing import Optional

from evaluation.adapters.base import AgentAdapter, ContainerHandle, WorkspaceContext
from evaluation.adapters.parsing import extract_assistant_text, extract_session_id
from evaluation.adapters.workspace import WorkspaceProvisioner
from evaluation.config.constants import REPO_ROOT, SERVICE_MANAGER_URL, SERVICES_NETWORK_NAME
from evaluation.config.relay import RelayConfig
from evaluation.config.settings import OpenClawAdapterConfig
from evaluation.infra.docker import ComposeClient, DockerClient
from evaluation.infra.gitlab import GitLabClient
from evaluation.infra.network import NetworkInspector
from evaluation.infra.shell import ShellExecutor
from evaluation.task.models import Round, Task, TurnResult


OPENCLAW_RUNTIME_HOME = "/home/node/.openclaw"


class OpenClawAdapter(AgentAdapter):
    name = "openclaw"

    def __init__(
        self,
        config: OpenClawAdapterConfig,
        *,
        shell: Optional[ShellExecutor] = None,
        docker: Optional[DockerClient] = None,
        gitlab: Optional[GitLabClient] = None,
        relay: Optional[RelayConfig] = None,
    ) -> None:
        super().__init__(config)
        self.shell = shell or ShellExecutor()
        self.docker = docker or DockerClient(self.shell)
        self.compose = ComposeClient(self.shell)
        self.network = NetworkInspector(self.shell, self.docker)
        self.gitlab = gitlab or GitLabClient(
            self.shell,
            provision_script=REPO_ROOT / "src" / "evaluation" / "infra" / "provision_gitlab_project.py",
        )
        self.relay = relay or RelayConfig()

    def ensure_dependencies(self) -> dict:
        ready = self.gitlab.gitlab_ready()
        if not ready["ok"]:
            sm_ready = self.gitlab.service_manager_ready()
            if not sm_ready["ok"]:
                return sm_ready
            self.gitlab.request_gitlab_up()
            ready = self.gitlab.gitlab_ready()
            if not ready["ok"]:
                return ready
        return {"ok": True, "relay_networks": self.network.discover_relay_networks()}

    def start(self, container_name: str) -> ContainerHandle:
        deps = self.ensure_dependencies()
        if not deps["ok"]:
            raise RuntimeError(f"openclaw dependencies unavailable: {deps.get('error')}")
        result = self.docker.run_detached(
            name=container_name,
            image=self.config.image,
            network=SERVICES_NETWORK_NAME,
            env=self._base_env(container_name),
            extra_args=["--network-alias", "openclaw-runner", "--user", "root"],
            volumes=[],
            security_opts=["no-new-privileges:true"],
            cap_drop=["ALL"],
            cap_add=["NET_RAW", "CHOWN", "SETUID", "SETGID", "DAC_OVERRIDE"],
            entrypoint="/bin/sh",
            cmd_args=[
                "-lc",
                (
                    f"mkdir -p {shlex.quote(self.config.workspace_root)} "
                    f"{OPENCLAW_RUNTIME_HOME}/sessions {OPENCLAW_RUNTIME_HOME}/logs; "
                    "chown -R node:node /home/node/.openclaw 2>/dev/null || true; "
                    "chmod -R u+rwX,go+rwX /home/node/.openclaw 2>/dev/null || true; "
                    "sleep infinity"
                ),
            ],
            timeout=180,
            read_only_rootfs=True,
            tmpfs_mounts=[
                "/tmp:exec,size=256M",
                "/home/node/.openclaw:exec,size=512M",
                "/root:exec,size=32M",
            ],
        )
        if not result.ok:
            raise RuntimeError(f"openclaw container start failed: {result.stderr or result.stdout}")
        for net in deps.get("relay_networks", []):
            if not self.network.connect(net, container_name):
                raise RuntimeError(f"failed to attach openclaw to {net}")
        return ContainerHandle(
            name=container_name,
            image=self.config.image,
            network=SERVICES_NETWORK_NAME,
            extra_networks=deps.get("relay_networks", []),
            meta={"service_manager_url": SERVICE_MANAGER_URL},
        )

    def _base_env(self, container_name: str) -> list[tuple[str, str]]:
        llm = getattr(self, "llm_config", None)
        if llm is not None:
            api_key = llm.api_key
            base_url = llm.base_url
            model = llm.model
        else:
            relay_env = self.relay.load_env()
            api_key = relay_env.get("LLM_RELAY_TOKEN") or relay_env.get("OPENAI_API_KEY") or ""
            base_url = relay_env.get("LLM_RELAY_BASE_URL") or relay_env.get("OPENAI_BASE_URL") or "http://llm-relay:4000/v1"
            model = relay_env.get("DEEPSEEK_MODEL", "deepseek-v4-pro").strip() or "deepseek-v4-pro"
        return [
            ("HOME", "/home/node"),
            ("PYTHONUNBUFFERED", "1"),
            ("OPENAI_API_KEY", api_key),
            ("OPENAI_BASE_URL", base_url),
            ("OPENAI_MODEL", model),
            ("OPENCLAW_RUN_ID", container_name),
        ]

    def prepare_runtime(self, handle: ContainerHandle, task: Task) -> dict:
        llm = getattr(self, "llm_config", None)
        model = (llm.model if llm is not None else "deepseek-v4-pro").strip() or "deepseek-v4-pro"
        base_url = (llm.base_url if llm is not None else "http://llm-relay:4000/v1").strip() or "http://llm-relay:4000/v1"
        api_key = (llm.api_key if llm is not None else "").strip()
        patch = {
            "models": {
                "mode": "merge",
                "providers": {
                    "memsecbench": {
                        "baseUrl": base_url,
                        "apiKey": api_key,
                        "api": "openai-completions",
                        "timeoutSeconds": int(self.config.timeout),
                        "models": [
                            {
                                "id": model,
                                "name": model,
                                "reasoning": False,
                                "input": ["text"],
                                "contextWindow": 200000,
                                "contextTokens": 128000,
                                "maxTokens": 8192,
                                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                                "compat": {"supportsDeveloperRole": False, "requiresStringContent": True},
                            }
                        ],
                    }
                },
            },
            "agents": {"defaults": {"model": f"memsecbench/{model}", "timeoutSeconds": int(self.config.timeout)}},
        }
        patch_json = json.dumps(patch, ensure_ascii=False)
        cmd = (
            "set -e; "
            f"cat > /tmp/openclaw-config.patch.json <<'JSON'\n{patch_json}\nJSON\n"
            "openclaw config patch --file /tmp/openclaw-config.patch.json >/tmp/openclaw-config-patch.out 2>&1; "
            f"openclaw models set {shlex.quote(f'memsecbench/{model}')} >>/tmp/openclaw-config-patch.out 2>&1; "
            "openclaw models list --json >>/tmp/openclaw-config-patch.out 2>&1; "
            "cat /tmp/openclaw-config-patch.out"
        )
        return self.docker.exec(handle.name, cmd, timeout=60).as_dict()

    def prepare_workspace(self, handle: ContainerHandle, task: Task) -> WorkspaceContext:
        provisioner = WorkspaceProvisioner(self.docker, self.gitlab, self.relay, self.shell)
        return provisioner.provision(
            handle.name,
            task,
            workspace_root=self.config.workspace_root,
            agent_name=self.name,
        )

    def run_round(
        self,
        handle: ContainerHandle,
        task: Task,
        round_data: Round,
        session_id: Optional[str],
    ) -> TurnResult:
        payload = self._build_payload(task, round_data)
        active_session = session_id or f"bench-{uuid.uuid4().hex[:12]}"
        shell_cmd = (
            "set -e; "
            f"cd {shlex.quote(self.config.workspace_root)}; "
            "openclaw agent --local --json "
            "--agent main "
            f"--model {shlex.quote(self._openclaw_model_id())} "
            f"--session-key {shlex.quote(f'agent:main:{active_session}')} "
            f"--timeout {int(self.config.timeout)} "
            f"--message {shlex.quote(payload)}"
        )
        result = self.docker.exec(handle.name, shell_cmd, timeout=self.config.timeout)
        combined = "\n".join(p for p in (result.stdout, result.stderr) if p)
        next_session_id = extract_session_id(combined) or active_session
        text = self._extract_agent_json_text(result.stdout) or extract_assistant_text(result.stdout, result.stderr)
        return TurnResult(
            turn=round_data.round,
            query=payload,
            assistant_response=text,
            ok=result.ok,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            command=" ".join(["docker", "exec", handle.name, "sh", "-lc", shell_cmd]),
            session_id=next_session_id,
            is_malicious=round_data.is_malicious,
            session_break=round_data.session_break,
            timed_out=result.timed_out,
            timeout_seconds=result.timeout_seconds,
            raw_payload=round_data.payload,
        )

    def _openclaw_model_id(self) -> str:
        llm = getattr(self, "llm_config", None)
        model = (llm.model if llm is not None else "deepseek-v4-pro").strip() or "deepseek-v4-pro"
        return f"memsecbench/{model}"

    @staticmethod
    def _extract_agent_json_text(stdout: str) -> str:
        text = (stdout or "").strip()
        if not text:
            return ""
        try:
            data = json.loads(text)
        except Exception:
            start = text.find("{")
            end = text.rfind("}")
            if start < 0 or end <= start:
                return ""
            try:
                data = json.loads(text[start : end + 1])
            except Exception:
                return ""
        if isinstance(data, dict):
            payloads = data.get("payloads")
            if isinstance(payloads, list):
                for payload in payloads:
                    if isinstance(payload, dict) and isinstance(payload.get("text"), str) and payload["text"].strip():
                        return payload["text"].strip()
            for key in ("reply", "response", "assistant_response", "assistant", "message", "text", "content", "output"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            for key in ("finalAssistantVisibleText", "finalAssistantRawText"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            meta = data.get("meta")
            if isinstance(meta, dict):
                for key in ("finalAssistantVisibleText", "finalAssistantRawText"):
                    value = meta.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
        return ""

    def export_artifacts(
        self,
        handle: ContainerHandle,
        task: Task,
        output_dir: Path,
        session_ids: list[str],
    ) -> dict:
        output_dir.mkdir(parents=True, exist_ok=True)
        exported: dict = {"sessions": [], "logs": {}}
        for sid in session_ids:
            if not sid:
                continue
            src = f"{OPENCLAW_RUNTIME_HOME}/sessions/session_{sid}.json"
            dst = output_dir / "runtime_artifacts" / "sessions" / f"session_{sid}.json"
            if self.docker.cp_from(handle.name, src, dst).ok:
                exported["sessions"].append(str(dst))
        for label, src in {
            "agent.log": f"{OPENCLAW_RUNTIME_HOME}/logs/agent.log",
            "errors.log": f"{OPENCLAW_RUNTIME_HOME}/logs/errors.log",
        }.items():
            dst = output_dir / "runtime_artifacts" / "logs" / label
            cp = self.docker.cp_from(handle.name, src, dst)
            exported["logs"][label] = str(dst) if cp.ok else None
        logs = self.docker.logs(handle.name)
        log_dst = output_dir / "runtime_artifacts" / "docker" / "container.log"
        log_dst.parent.mkdir(parents=True, exist_ok=True)
        log_dst.write_text((logs.stdout or "") + (("\n" + logs.stderr) if logs.stderr else ""), encoding="utf-8")
        exported["docker_logs"] = str(log_dst)
        git_state = self._export_git_workspace_state(handle.name, task, output_dir)
        if git_state:
            exported["git_workspace_state"] = git_state
        return exported

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

    def cleanup(
        self,
        handle: ContainerHandle,
        workspace: Optional[WorkspaceContext],
        keep_container: bool = False,
    ) -> dict:
        gitlab_project = (workspace.service_context or {}).get("gitlab_project") if workspace and workspace.service_context else None
        gitlab_cleanup = (
            self.gitlab.cleanup_project(gitlab_project)
            if gitlab_project
            else {"ok": False, "error": "GitLab project missing during cleanup"}
        )
        if not keep_container:
            self.docker.remove(handle.name)
        return {"container_removed": not keep_container, "gitlab_cleanup": gitlab_cleanup}

    @staticmethod
    def _build_payload(task: Task, round_data: Round) -> str:
        return (round_data.payload or task.instruction or "").strip()
