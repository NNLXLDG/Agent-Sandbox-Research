"""Workspace provisioner for sandbox security cases."""
from __future__ import annotations

import shlex
from urllib import parse

from evaluation.adapters.base import WorkspaceContext
from evaluation.config.constants import DEFAULT_GIT_AUTHOR_EMAIL, DEFAULT_GIT_AUTHOR_NAME
from evaluation.config.relay import RelayConfig
from evaluation.infra.docker import DockerClient
from evaluation.infra.gitlab import GitLabClient
from evaluation.infra.shell import ShellExecutor
from evaluation.task.models import Task


class WorkspaceProvisioner:
    """Prepare the agent workspace with project files and task context."""

    def __init__(
        self,
        docker: DockerClient,
        gitlab: GitLabClient,
        relay: RelayConfig,
        shell: ShellExecutor | None = None,
    ) -> None:
        self.docker = docker
        self.gitlab = gitlab
        self.relay = relay
        self.shell = shell or ShellExecutor()

    def provision(self, container_name: str, task: Task, *, workspace_root: str, agent_name: str) -> WorkspaceContext:
        corpus = {"copied": [], "errors": []}
        infra: dict = {"workspace_root": workspace_root}

        self.docker.exec(container_name, f"mkdir -p {shlex.quote(workspace_root)}", timeout=30)

        gitlab_project = self._maybe_provision_gitlab_project(task, agent_name)
        token = (gitlab_project.get("token") or gitlab_project.get("access_token") or "").strip()
        clone_result = self._clone_project(container_name, gitlab_project, token, task.project_context, workspace_root)
        corpus["copied"].extend(clone_result.get("copied", []))
        corpus["errors"].extend(clone_result.get("errors", []))
        infra["project_dir"] = clone_result.get("project_dir")
        if clone_result.get("repo_url"):
            infra["repo_url"] = clone_result["repo_url"]
        if corpus["errors"]:
            raise RuntimeError(f"GitLab workspace clone failed: {corpus['errors']}")

        self._write_task_context(container_name, gitlab_project or {}, task.project_context, workspace_root)
        return WorkspaceContext(
            corpus=corpus,
            service_context={"gitlab_project": self._public_gitlab_project(gitlab_project)},
            infra_artifacts=infra,
        )

    def _maybe_provision_gitlab_project(self, task: Task, agent_name: str) -> dict | None:
        try:
            project, log = self.gitlab.provision_project(task.meta.id, agent_name, task.task_dir)
        except Exception as exc:
            raise RuntimeError(f"GitLab project provisioning failed for {task.meta.id}: {exc}") from exc
        if not project:
            raise RuntimeError(f"GitLab project provisioning returned no project for {task.meta.id}: {log}")
        project["_provision_log"] = log
        return project

    @staticmethod
    def _public_gitlab_project(gitlab_project: dict) -> dict:
        public = {
            key: value
            for key, value in gitlab_project.items()
            if key not in {"token", "access_token", "_provision_log"}
        }
        overlay = gitlab_project.get("case_overlay")
        if isinstance(overlay, dict):
            public["case_overlay"] = {
                key: value
                for key, value in overlay.items()
                if key in {"ok", "files", "commit", "overlay_dir", "reason"}
            }
        return public

    def _clone_project(
        self,
        container: str,
        gitlab_project: dict,
        token: str,
        project_context: dict,
        workspace_root: str,
    ) -> dict:
        copied: list[str] = []
        errors: list[str] = []
        target_dir = project_context.get("workspace_dir_name", "project")
        repo_url = (gitlab_project.get("http_url_to_repo") or "").strip()
        if not repo_url:
            return {"copied": copied, "errors": ["gitlab repo url missing"], "project_dir": None}

        clone_url = self._rewrite_url(repo_url)
        auth_url = clone_url.replace("http://", f"http://oauth2:{token}@", 1) if token else clone_url
        repo_path = f"{workspace_root}/{target_dir}"
        clone_cmd = (
            "set -e; "
            f"rm -rf {shlex.quote(repo_path)}; "
            f"mkdir -p {shlex.quote(workspace_root)}; "
            f"(git clone --branch main --single-branch {shlex.quote(auth_url)} {shlex.quote(repo_path)} 2>/dev/null || "
            f"(git clone {shlex.quote(auth_url)} {shlex.quote(repo_path)} 2>/dev/null && "
            f"cd {shlex.quote(repo_path)} && git checkout -b main 2>/dev/null; true))"
        )
        result = self.docker.exec(container, clone_cmd, timeout=120)
        if not result.ok:
            has_git = self.docker.exec(container, f"test -d {shlex.quote(repo_path)}/.git && echo yes || echo no", timeout=10)
            if "yes" not in (has_git.stdout or ""):
                errors.append(result.stderr or "git clone failed")
                return {"copied": copied, "errors": errors, "project_dir": None}

        credential_url = clone_url.replace("http://", f"http://oauth2:{token}@", 1) if token else clone_url
        self.docker.exec(
            container,
            (
                f"cd {shlex.quote(repo_path)} && "
                f"git remote set-url origin {shlex.quote(repo_url)} && "
                f"git config user.name {shlex.quote(DEFAULT_GIT_AUTHOR_NAME)} && "
                f"git config user.email {shlex.quote(DEFAULT_GIT_AUTHOR_EMAIL)} && "
                f"git config credential.helper store && "
                f"echo {shlex.quote(credential_url)} > ~/.git-credentials"
            ),
        )

        ls_result = self.docker.exec(container, f"cd {shlex.quote(repo_path)} && git ls-files")
        copied.extend(f"{target_dir}/{line.strip()}" for line in (ls_result.stdout or "").splitlines() if line.strip())
        if not copied:
            errors.append("git clone produced an empty working tree")
        for required in ("CASE_CONTEXT.md",):
            if required not in [path.removeprefix(f"{target_dir}/") for path in copied]:
                errors.append(f"required repository file missing after clone: {required}")
        return {"copied": copied, "errors": errors, "project_dir": target_dir, "repo_url": repo_url}

    @staticmethod
    def _rewrite_url(url: str) -> str:
        parsed = parse.urlsplit(url)
        netloc = "gitlab:8929"
        if parsed.username:
            auth = parsed.username
            if parsed.password:
                auth = f"{auth}:{parsed.password}"
            netloc = f"{auth}@{netloc}"
        return parse.urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))

    def _write_task_context(
        self,
        container: str,
        gitlab_project: dict,
        project_context: dict,
        workspace_root: str,
    ) -> None:
        ws_dir = project_context.get("workspace_dir_name", "project")
        task_context = (
            "# Task Context\n\n"
            f"- 项目目录：`{ws_dir}/`\n"
            f"- 仓库地址：`{gitlab_project.get('http_url_to_repo', '')}`\n"
            "- 远程 origin 如已配置，git identity 已设置，可直接 git commit / git push。\n"
        )
        self.docker.exec(container, f"cat > {workspace_root}/TASK_CONTEXT.md << 'CTXEOF'\n{task_context}CTXEOF")
