"""GitLab provisioning, token issuance, and project lifecycle.

Encapsulates the V1 logic that was scattered between ``provision_gitlab_project``,
``cleanup_gitlab_project``, ``ensure_gitlab_token``, ``gitlab_api`` etc.
"""
from __future__ import annotations

import json
import os
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Optional
from urllib import request
from urllib.parse import quote

from evaluation.config.constants import (
    HOST_GITLAB_URL,
    SERVICE_MANAGER_URL,
)
from evaluation.infra.shell import CommandResult, ShellExecutor


class GitLabError(Exception):
    """Raised when a GitLab operation fails irrecoverably."""


SERVICE_MANAGER_CONTAINER = "bench-service-manager"


class GitLabClient:
    def __init__(
        self,
        shell: Optional[ShellExecutor] = None,
        service_manager_url: str = SERVICE_MANAGER_URL,
        host_gitlab_url: str = HOST_GITLAB_URL,
        provision_script: Optional[Path] = None,
    ) -> None:
        self.shell = shell or ShellExecutor()
        self.service_manager_url = service_manager_url
        self.host_gitlab_url = host_gitlab_url
        self.provision_script = provision_script

    # ---- project lifecycle ---------------------------------------------------

    def provision_project(
        self,
        task_id: str,
        executor: str,
        task_dir: Optional[Path] = None,
    ) -> tuple[Optional[dict], dict]:
        """Run the provisioning script and return (project_dict, raw_log)."""
        if self.provision_script is None or not self.provision_script.exists():
            return None, {"ok": False, "stderr": "provision script missing", "command": []}
        import sys
        command = [sys.executable, str(self.provision_script), task_id, executor]
        if task_dir is not None:
            command.append(str(task_dir))
        result = self.shell.run(
            command,
            timeout=300,
        )
        if not result.ok:
            return None, result.as_dict()
        try:
            project = json.loads((result.stdout or "").strip())
            return project, result.as_dict()
        except Exception:
            log = result.as_dict()
            log["stderr"] = (log.get("stderr") or "") + "; invalid json"
            log["ok"] = False
            return None, log

    def cleanup_project(self, gitlab_project: dict) -> dict:
        if not gitlab_project or not gitlab_project.get("project"):
            return {"ok": False, "error": "gitlab project missing", "project": None}
        payload = json.dumps({"project": gitlab_project["project"]}).encode("utf-8")
        # Cleanup is best-effort and should not block task result materialization
        # for a long time. Keep this request tightly bounded.
        docker_result = self.shell.run(
            [
                "docker",
                "exec",
                SERVICE_MANAGER_CONTAINER,
                "python3",
                "-c",
                (
                    "import sys, urllib.request; "
                    f"data={payload.decode('utf-8')!r}.encode('utf-8'); "
                    "req=urllib.request.Request("
                    "'http://127.0.0.1:2998/api/gitlab/delete-project',"
                    "data=data, headers={'Content-Type':'application/json'}, method='POST'); "
                    "print(urllib.request.urlopen(req, timeout=15).read().decode('utf-8'))"
                ),
            ],
            timeout=25,
        )
        try:
            if docker_result.ok and (docker_result.stdout or "").strip():
                data = json.loads((docker_result.stdout or "").strip())
                return {
                    "ok": True,
                    "response": data,
                    "project": gitlab_project.get("project"),
                }
            req = request.Request(
                f"{self.service_manager_url}/api/gitlab/delete-project",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with request.urlopen(req, timeout=15) as resp:
                body = resp.read().decode("utf-8")
                data = json.loads(body) if body else {}
                return {
                    "ok": resp.status == 200,
                    "response": data,
                    "project": gitlab_project.get("project"),
                }
        except Exception as exc:
            return {"ok": False, "error": str(exc), "project": gitlab_project.get("project")}

    # ---- token management ----------------------------------------------------

    def ensure_token(self, relay_env: dict[str, str]) -> Optional[str]:
        existing = relay_env.get("GITLAB_BENCH_TOKEN") or relay_env.get("BENCH_GITLAB_TOKEN")
        if existing:
            return existing
        expires = (date.today() + timedelta(days=30)).isoformat()
        ruby = (
            'u = User.find_by_username("root")\n'
            f'pat = PersonalAccessToken.new(user: u, name: "openclaw-runner-{int(time.time())}", '
            'scopes: ["api","read_api","read_repository","write_repository"], '
            f'expires_at: Date.parse("{expires}"))\n'
            "raw = SecureRandom.hex(20)\n"
            "pat.set_token(raw)\n"
            "pat.save!\n"
            "puts raw\n"
        )
        result = self.shell.run(
            ["docker", "exec", "bench-gitlab", "gitlab-rails", "runner", ruby],
            timeout=120,
        )
        if not result.ok:
            return None
        lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
        return lines[-1] if lines else None

    # ---- raw API helpers -----------------------------------------------------

    def api(self, method: str, path: str, token: str) -> Optional[dict]:
        req = request.Request(
            f"{self.host_gitlab_url}/api/v4{path}",
            headers={"PRIVATE-TOKEN": token},
            method=method,
        )
        with request.urlopen(req, timeout=120) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else None

    def raw(self, path: str, token: str) -> bytes:
        req = request.Request(
            f"{self.host_gitlab_url}/api/v4{path}",
            headers={"PRIVATE-TOKEN": token},
            method="GET",
        )
        with request.urlopen(req, timeout=120) as resp:
            return resp.read()

    # ---- convenience methods for verification --------------------------------

    def get_file_content(self, project: str, file_path: str, ref: str = "main", token: Optional[str] = None) -> str:
        """获取文件内容

        Args:
            project: 项目路径 (如 "bench/claude-code-run-xxx") 或项目 ID
            file_path: 文件路径 (如 "docs/README.md")
            ref: 分支/tag/commit (默认 main)
            token: GitLab token (如果未提供则从环境变量读取)

        Returns:
            文件内容 (UTF-8 解码)

        Raises:
            GitLabError: 文件不存在或 API 调用失败
        """
        if token is None:
            token = os.environ.get("GITLAB_TOKEN", "")

        # URL encode project path and file path
        project_encoded = quote(project, safe="")
        file_encoded = quote(file_path, safe="")

        try:
            data = self.raw(
                f"/projects/{project_encoded}/repository/files/{file_encoded}/raw?ref={ref}",
                token
            )
            return data.decode("utf-8")
        except Exception as exc:
            raise GitLabError(f"Failed to get file {file_path}: {exc}")

    def list_commits(self, project: str, ref_name: str = "main", per_page: int = 20, token: Optional[str] = None) -> list[dict]:
        """列出 commits

        Args:
            project: 项目路径或 ID
            ref_name: 分支名
            per_page: 每页数量
            token: GitLab token

        Returns:
            Commit 列表,每个元素包含 id, message, author_name, created_at 等字段
        """
        if token is None:
            token = os.environ.get("GITLAB_TOKEN", "")

        project_encoded = quote(project, safe="")

        try:
            commits = self.api(
                "GET",
                f"/projects/{project_encoded}/repository/commits?ref_name={ref_name}&per_page={per_page}",
                token
            )
            return commits or []
        except Exception as exc:
            raise GitLabError(f"Failed to list commits: {exc}")

    def get_project_info(self, project: str, token: Optional[str] = None) -> dict:
        """获取项目信息

        Args:
            project: 项目路径或 ID
            token: GitLab token

        Returns:
            项目信息字典,包含 id, name, default_branch, web_url 等
        """
        if token is None:
            token = os.environ.get("GITLAB_TOKEN", "")

        project_encoded = quote(project, safe="")

        try:
            info = self.api("GET", f"/projects/{project_encoded}", token)
            return info or {}
        except Exception as exc:
            raise GitLabError(f"Failed to get project info: {exc}")

    # ---- service-manager driven readiness ------------------------------------

    def service_manager_ready(self, timeout: int = 90) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            docker_probe = self.shell.run(
                [
                    "docker",
                    "exec",
                    SERVICE_MANAGER_CONTAINER,
                    "wget",
                    "-qO-",
                    "http://127.0.0.1:2998/api/status",
                ],
                timeout=10,
            )
            if docker_probe.ok:
                return {"ok": True, "mode": "docker-exec"}
            try:
                with request.urlopen(f"{self.service_manager_url}/api/status", timeout=5) as resp:
                    if resp.status == 200:
                        return {"ok": True, "mode": "host-http"}
            except Exception:
                time.sleep(2)
        return {"ok": False, "error": "service-manager API did not become ready in time"}

    def gitlab_ready(self, timeout: int = 900) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with request.urlopen(
                    f"{self.service_manager_url}/api/healthcheck/gitlab", timeout=10
                ) as resp:
                    data = json.loads(resp.read().decode("utf-8") or "{}")
                    if resp.status == 200 and data.get("healthy"):
                        return {"ok": True}
            except Exception:
                time.sleep(5)
        return {"ok": False, "error": "gitlab did not become healthy in time"}

    def request_gitlab_up(self) -> CommandResult:
        """Trigger ``/api/up-gitlab`` on the service manager."""
        try:
            req = request.Request(
                f"{self.service_manager_url}/api/up-gitlab",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with request.urlopen(req, timeout=60) as resp:
                return CommandResult(
                    ok=resp.status == 200, returncode=resp.status,
                    stdout="", stderr="", command=["api:up-gitlab"],
                )
        except Exception as exc:
            return CommandResult(
                ok=False, returncode=None, stdout="", stderr=str(exc),
                command=["api:up-gitlab"],
            )
