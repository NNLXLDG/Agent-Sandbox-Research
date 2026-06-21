#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib import error, parse, request


def resolve_project_root() -> Path:
    configured = Path(os.environ.get("SERVICE_MANAGER_PROJECT_ROOT", "/workspace"))
    if (configured / "infra" / "services").exists():
        return configured
    return Path(__file__).resolve().parents[3]


PROJECT_ROOT = resolve_project_root()
HOST_PROJECT_ROOT = Path(os.environ.get("HOST_PROJECT_ROOT", str(PROJECT_ROOT)))
LOG_DIR = PROJECT_ROOT / "infra" / "services" / "logs"
NETWORK_NAME = os.environ.get("BENCH_SERVICES_NETWORK", "bench-services-net")
GITLAB_CONTAINER = os.environ.get("BENCH_GITLAB_CONTAINER", "bench-gitlab")
GITLAB_IMAGE = os.environ.get("BENCH_GITLAB_IMAGE", "yrzr/gitlab-ce-arm64v8:17.0.0-ce.0")
GITLAB_HTTP_PORT = os.environ.get("BENCH_GITLAB_HTTP_PORT", "8929")
GITLAB_SSH_PORT = os.environ.get("BENCH_GITLAB_SSH_PORT", "2224")
GITLAB_URL = os.environ.get("BENCH_GITLAB_URL", "http://gitlab:8929")
GITLAB_GROUP = os.environ.get("BENCH_GITLAB_GROUP", "bench")
DEFAULT_TEMPLATE_PROJECT = os.environ.get("BENCH_GITLAB_TEMPLATE_PROJECT", "agent-sandbox-template")
MAILPIT_CONTAINER = os.environ.get("BENCH_MAILPIT_CONTAINER", "bench-mailpit")
MAILPIT_HTTP_PORT = os.environ.get("BENCH_MAILPIT_HTTP_PORT", "8025")
MAILPIT_SMTP_PORT = os.environ.get("BENCH_MAILPIT_SMTP_PORT", "1025")
SERVICE_MANAGER_PORT = int(os.environ.get("SERVICE_MANAGER_PORT", "2998"))


def run(cmd: list[str], check: bool = True, capture: bool = True, cwd: Path | None = None) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, text=True, capture_output=capture, cwd=cwd)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(cmd)}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
    return result


def ensure_dirs() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def ensure_network() -> dict:
    result = run(["docker", "network", "ls", "--format", "{{.Name}}"], check=False)
    if NETWORK_NAME in result.stdout.split():
        return {"created": False, "network": NETWORK_NAME}
    run(["docker", "network", "create", NETWORK_NAME])
    return {"created": True, "network": NETWORK_NAME}


def container_exists(name: str) -> bool:
    result = run(
        ["docker", "ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Names}}"],
        check=False,
    )
    return name in result.stdout.splitlines()


def container_running(name: str) -> bool:
    result = run(
        ["docker", "ps", "--filter", f"name=^{name}$", "--format", "{{.Names}}"],
        check=False,
    )
    return name in result.stdout.splitlines()


def gitlab_probe_urls() -> list[str]:
    host_root = f"http://127.0.0.1:{GITLAB_HTTP_PORT}"
    return [
        f"{GITLAB_URL.rstrip('/')}/api/v4/version",
        f"{host_root}/api/v4/version",
        f"{host_root}/users/sign_in",
    ]


def url_reachable(url: str) -> bool:
    try:
        with request.urlopen(request.Request(url, method="GET"), timeout=5) as response:
            return response.status == 200
    except error.HTTPError as exc:
        return exc.code in (200, 401, 403)
    except Exception:
        return False


def resolve_gitlab_url() -> str:
    for url in gitlab_probe_urls():
        if url_reachable(url):
            return url.rsplit("/api/v4/version", 1)[0].rsplit("/users/sign_in", 1)[0]
    return GITLAB_URL


def api(method: str, path: str, token: str, payload: dict | None = None):
    headers = {"PRIVATE-TOKEN": token} if token else {}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(f"{resolve_gitlab_url()}/api/v4{path}", data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=30) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else None
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code in (400, 401, 404, 409):
            return {"_error_code": exc.code, "_body": body}
        raise RuntimeError(f"api {method} {path} failed: {exc.code} {body}") from exc


def ensure_token() -> str:
    expires = (date.today() + timedelta(days=30)).isoformat()
    ruby = f'''u = User.first || User.new(username: "root", email: "admin@example.com", name: "Administrator", admin: true, confirmed_at: Time.now, password: "Password123!", password_confirmation: "Password123!")
u.skip_confirmation! if u.respond_to?(:skip_confirmation!)
u.save!(validate: false)
pat = PersonalAccessToken.new(user: u, name: "agent-sandbox-seeder-{int(time.time())}", scopes: ["api","read_api","read_repository","write_repository"], expires_at: Date.parse("{expires}"))
raw = SecureRandom.hex(20)
pat.set_token(raw)
pat.save!
puts raw
'''
    result = run(["docker", "exec", GITLAB_CONTAINER, "gitlab-rails", "runner", ruby])
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("failed to produce GitLab personal access token")
    return lines[-1]


def up_gitlab() -> dict:
    ensure_dirs()
    ensure_network()
    if container_exists(GITLAB_CONTAINER):
        if container_running(GITLAB_CONTAINER):
            return {"status": "already_running", "container": GITLAB_CONTAINER}
        run(["docker", "start", GITLAB_CONTAINER])
        return {"status": "started_existing", "container": GITLAB_CONTAINER}

    for volume in ["bench-gitlab-config", "bench-gitlab-logs", "bench-gitlab-data"]:
        run(["docker", "volume", "create", volume], check=False)

    omnibus = (
        'external_url "http://gitlab:8929"; '
        'gitlab_rails["gitlab_shell_ssh_port"] = 22; '
        'gitlab_rails["initial_root_password"] = "Password123!"; '
        'gitlab_rails["store_initial_root_password"] = false;'
    )
    run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            GITLAB_CONTAINER,
            "--hostname",
            "gitlab",
            "--network",
            NETWORK_NAME,
            "-p",
            f"{GITLAB_HTTP_PORT}:8929",
            "-p",
            f"{GITLAB_SSH_PORT}:22",
            "-e",
            f"GITLAB_OMNIBUS_CONFIG={omnibus}",
            "-v",
            "bench-gitlab-config:/etc/gitlab",
            "-v",
            "bench-gitlab-logs:/var/log/gitlab",
            "-v",
            "bench-gitlab-data:/var/opt/gitlab",
            "--shm-size",
            "256m",
            GITLAB_IMAGE,
        ]
    )
    return {"status": "started_new", "container": GITLAB_CONTAINER}


def down_gitlab() -> dict:
    if not container_exists(GITLAB_CONTAINER):
        return {"status": "not_found", "container": GITLAB_CONTAINER}
    run(["docker", "rm", "-f", GITLAB_CONTAINER])
    return {"status": "removed", "container": GITLAB_CONTAINER}


def wait_gitlab(timeout: int = 900) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if container_running(GITLAB_CONTAINER) and any(url_reachable(url) for url in gitlab_probe_urls()):
            return {"healthy": True, "container": GITLAB_CONTAINER}
        time.sleep(10)
    raise RuntimeError("gitlab did not become healthy before timeout")


def seed_template() -> dict:
    script = PROJECT_ROOT / "infra" / "services" / "bootstrap" / "seed_gitlab.py"
    env = os.environ.copy()
    env["SERVICE_MANAGER_PROJECT_ROOT"] = str(PROJECT_ROOT)
    env["BENCH_GITLAB_URL"] = resolve_gitlab_url()
    env["BENCH_GITLAB_GROUP"] = GITLAB_GROUP
    env["BENCH_GITLAB_TEMPLATE_PROJECT"] = DEFAULT_TEMPLATE_PROJECT
    env["BENCH_GITLAB_TOKEN"] = ensure_token()
    result = subprocess.run(
        [sys.executable, str(script)],
        text=True,
        capture_output=True,
        env=env,
        cwd=str(PROJECT_ROOT),
    )
    if result.returncode != 0:
        raise RuntimeError(f"seed_gitlab failed\nstdout={result.stdout}\nstderr={result.stderr}")
    text = result.stdout.strip()
    return json.loads(text[text.find("{") :])


def create_fresh_project(project_name: str, template_project: str | None = None) -> dict:
    token = ensure_token()
    group_path = parse.quote(GITLAB_GROUP, safe="")
    groups = api("GET", f"/groups?search={parse.quote(GITLAB_GROUP)}", token)
    group = next((item for item in groups if item["path"] == GITLAB_GROUP), None)
    if not group:
        seed_template()
        groups = api("GET", f"/groups?search={parse.quote(GITLAB_GROUP)}", token)
        group = next((item for item in groups if item["path"] == GITLAB_GROUP), None)
    if not group:
        raise RuntimeError(f"group not found: {GITLAB_GROUP}")

    source = template_project or DEFAULT_TEMPLATE_PROJECT
    template = api("GET", f"/projects/{parse.quote(f'{GITLAB_GROUP}/{source}', safe='')}", token)
    if isinstance(template, dict) and template.get("_error_code"):
        seed_template()
        template = api("GET", f"/projects/{parse.quote(f'{GITLAB_GROUP}/{source}', safe='')}", token)
    if isinstance(template, dict) and template.get("_error_code"):
        raise RuntimeError(f"template project not found: {GITLAB_GROUP}/{source}")

    created = api(
        "POST",
        "/projects",
        token,
        {
            "name": project_name,
            "path": project_name,
            "namespace_id": group["id"],
            "visibility": "private",
            "initialize_with_readme": False,
        },
    )
    if isinstance(created, dict) and created.get("_error_code"):
        raise RuntimeError(f"failed to create project: {created}")

    source_url = template["http_url_to_repo"].replace("http://", f"http://oauth2:{token}@")
    target_url = created["http_url_to_repo"].replace("http://", f"http://oauth2:{token}@")
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo.git"
        run(["git", "clone", "--mirror", source_url, str(repo)])
        run(["git", "remote", "set-url", "origin", target_url], cwd=repo)
        run(["git", "push", "--all", "--force", "origin"], cwd=repo)
        run(["git", "push", "--tags", "--force", "origin"], cwd=repo, check=False)

    return {
        "project": created["path_with_namespace"],
        "http_url_to_repo": created["http_url_to_repo"],
        "source_template": template["path_with_namespace"],
        "group": group_path,
        "token": token,
    }


def is_safe_run_project(project_path: str) -> bool:
    if not project_path:
        return False
    expected_prefix = f"{GITLAB_GROUP}/"
    if not project_path.startswith(expected_prefix):
        return False
    project_name = project_path[len(expected_prefix) :]
    return bool(project_name) and "-run-" in project_name and not project_name.endswith("-template")


def delete_run_project(project_path: str) -> dict:
    if not is_safe_run_project(project_path):
        return {"status": "skipped_unsafe_name", "project": project_path}
    token = ensure_token()
    project = api("GET", f"/projects/{parse.quote(project_path, safe='')}", token)
    if isinstance(project, dict) and project.get("_error_code") == 404:
        return {"status": "not_found", "project": project_path}
    if isinstance(project, dict) and project.get("_error_code"):
        raise RuntimeError(f"failed to resolve project for delete: {project}")
    deleted = api("DELETE", f"/projects/{project['id']}", token)
    if isinstance(deleted, dict) and deleted.get("_error_code") == 404:
        return {"status": "not_found", "project": project_path}
    if isinstance(deleted, dict) and deleted.get("_error_code"):
        raise RuntimeError(f"failed to delete project: {deleted}")
    return {"status": "deleted", "project": project_path}


def status() -> dict:
    ensure_dirs()
    return {
        "network": NETWORK_NAME,
        "gitlab_container": GITLAB_CONTAINER,
        "gitlab_exists": container_exists(GITLAB_CONTAINER),
        "gitlab_running": container_running(GITLAB_CONTAINER),
        "gitlab_http_port": GITLAB_HTTP_PORT,
        "gitlab_ssh_port": GITLAB_SSH_PORT,
        "mailpit_container": MAILPIT_CONTAINER,
        "mailpit_exists": container_exists(MAILPIT_CONTAINER),
        "mailpit_running": container_running(MAILPIT_CONTAINER),
        "mailpit_http_port": MAILPIT_HTTP_PORT,
        "mailpit_smtp_port": MAILPIT_SMTP_PORT,
        "project_root": str(PROJECT_ROOT),
        "host_project_root": str(HOST_PROJECT_ROOT),
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, obj: dict) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        try:
            if self.path == "/api/status":
                self._send(200, status())
            elif self.path == "/api/healthcheck/gitlab":
                healthy = container_running(GITLAB_CONTAINER) and any(
                    url_reachable(url) for url in gitlab_probe_urls()
                )
                self._send(200, {"healthy": healthy, "container": GITLAB_CONTAINER})
            else:
                self._send(404, {"error": "not_found"})
        except Exception as exc:
            self._send(500, {"error": str(exc)})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length else b"{}"
        payload = json.loads(body.decode("utf-8") or "{}")
        try:
            if self.path == "/api/up-gitlab":
                self._send(200, up_gitlab())
            elif self.path == "/api/down-gitlab":
                self._send(200, down_gitlab())
            elif self.path == "/api/wait-gitlab":
                self._send(200, wait_gitlab())
            elif self.path == "/api/gitlab/seed-template":
                self._send(200, seed_template())
            elif self.path == "/api/gitlab/create-project-from-template":
                name = payload.get("project_name")
                if not name:
                    self._send(400, {"error": "project_name required"})
                else:
                    self._send(200, create_fresh_project(name, payload.get("template_project")))
            elif self.path == "/api/gitlab/delete-project":
                project = payload.get("project")
                if not project:
                    self._send(400, {"error": "project required"})
                else:
                    self._send(200, delete_run_project(project))
            else:
                self._send(404, {"error": "not_found"})
        except Exception as exc:
            self._send(500, {"error": str(exc)})


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "api":
        ensure_dirs()
        server = HTTPServer(("0.0.0.0", SERVICE_MANAGER_PORT), Handler)
        print(f"[service-manager] api listening on :{SERVICE_MANAGER_PORT}")
        server.serve_forever()
        return 0
    print("usage: manage_services.py api")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
