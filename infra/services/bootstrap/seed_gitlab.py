#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib import error, parse, request


GITLAB_URL = os.environ.get("BENCH_GITLAB_URL", "http://gitlab:8929").rstrip("/")
GROUP_NAME = os.environ.get("BENCH_GITLAB_GROUP", "bench")
TEMPLATE_PROJECT = os.environ.get("BENCH_GITLAB_TEMPLATE_PROJECT", "agent-sandbox-template")
TOKEN = os.environ.get("BENCH_GITLAB_TOKEN", "")


def resolve_repo_root() -> Path:
    configured = Path(os.environ.get("SERVICE_MANAGER_PROJECT_ROOT", "/workspace"))
    if (configured / "infra" / "services").exists():
        return configured
    return Path(__file__).resolve().parents[3]


REPO_ROOT = resolve_repo_root()
SOURCE_DIR = REPO_ROOT / "sandbox" / "project"


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(cmd)}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
    return result


def api(method: str, path: str, payload: dict | None = None):
    data = None
    headers = {"PRIVATE-TOKEN": TOKEN} if TOKEN else {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(f"{GITLAB_URL}/api/v4{path}", data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=30) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else None
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code in (400, 401, 404, 409):
            return {"_error_code": exc.code, "_body": body}
        raise RuntimeError(f"api {method} {path} failed: {exc.code} {body}") from exc


def ensure_group() -> dict:
    groups = api("GET", f"/groups?search={parse.quote(GROUP_NAME)}")
    if isinstance(groups, list):
        for group in groups:
            if group["path"] == GROUP_NAME:
                return group
    created = api("POST", "/groups", {"name": GROUP_NAME, "path": GROUP_NAME})
    if isinstance(created, dict) and created.get("_error_code") and created["_error_code"] != 409:
        raise RuntimeError(f"failed to create group: {created}")
    groups = api("GET", f"/groups?search={parse.quote(GROUP_NAME)}")
    for group in groups:
        if group["path"] == GROUP_NAME:
            return group
    raise RuntimeError("group not found after create")


def ensure_project(group_id: int) -> dict:
    projects = api("GET", f"/groups/{group_id}/projects?search={parse.quote(TEMPLATE_PROJECT)}")
    if isinstance(projects, list):
        for project in projects:
            if project["path"] == TEMPLATE_PROJECT:
                return project
    created = api(
        "POST",
        "/projects",
        {
            "name": TEMPLATE_PROJECT,
            "path": TEMPLATE_PROJECT,
            "namespace_id": group_id,
            "initialize_with_readme": False,
            "visibility": "private",
        },
    )
    if isinstance(created, dict) and created.get("_error_code") and created["_error_code"] != 409:
        raise RuntimeError(f"failed to create project: {created}")
    projects = api("GET", f"/groups/{group_id}/projects?search={parse.quote(TEMPLATE_PROJECT)}")
    for project in projects:
        if project["path"] == TEMPLATE_PROJECT:
            return project
    raise RuntimeError("project not found after create")


def iter_source_files(source_dir: Path):
    for path in sorted(source_dir.rglob("*")):
        if ".git" in path.parts:
            continue
        if path.is_file():
            yield path


def seed_repo(http_url: str) -> dict:
    if not TOKEN:
        raise RuntimeError("BENCH_GITLAB_TOKEN is required")
    if not SOURCE_DIR.exists():
        raise RuntimeError(f"template source directory missing: {SOURCE_DIR}")
    if remote_main_exists(http_url):
        return {"status": "already_seeded", "branch": "main"}
    with tempfile.TemporaryDirectory() as tmp:
        worktree = Path(tmp)
        for path in iter_source_files(SOURCE_DIR):
            rel = path.relative_to(SOURCE_DIR)
            dest = worktree / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
        run(["git", "init"], cwd=worktree)
        run(["git", "config", "user.email", "bench@example.local"], cwd=worktree)
        run(["git", "config", "user.name", "Agent Sandbox Seeder"], cwd=worktree)
        run(["git", "add", "."], cwd=worktree)
        run(["git", "commit", "-m", "Initial agent sandbox project"], cwd=worktree)
        auth_url = http_url.replace("http://", f"http://oauth2:{TOKEN}@")
        run(["git", "branch", "-M", "main"], cwd=worktree)
        run(["git", "remote", "add", "origin", auth_url], cwd=worktree)
        run(["git", "push", "-u", "origin", "main"], cwd=worktree)
    return {"status": "seeded", "branch": "main"}


def remote_main_exists(http_url: str) -> bool:
    auth_url = http_url.replace("http://", f"http://oauth2:{TOKEN}@")
    result = subprocess.run(
        ["git", "ls-remote", "--heads", auth_url, "main"],
        text=True,
        capture_output=True,
    )
    return result.returncode == 0 and bool((result.stdout or "").strip())


def main() -> int:
    group = ensure_group()
    project = ensure_project(group["id"])
    seed_result = seed_repo(project["http_url_to_repo"])
    print(
        json.dumps(
            {
                "group": group["full_path"],
                "template_project": project["path_with_namespace"],
                "http_url_to_repo": project["http_url_to_repo"],
                "source_dir": str(SOURCE_DIR),
                "seed": seed_result,
                "reset_strategy": "Create fresh per-run GitLab project from this sandbox/project template.",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
