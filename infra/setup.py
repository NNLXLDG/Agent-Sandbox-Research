#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib import request


REPO_ROOT = Path(__file__).resolve().parent.parent
SERVICES_NETWORK = "bench-services-net"
SERVICES_COMPOSE = REPO_ROOT / "infra" / "services" / "docker-compose.yml"
SANDBOX_COMPOSE = REPO_ROOT / "infra" / "sandbox" / "docker-compose.yml"
SERVICE_MANAGER_URL = "http://127.0.0.1:2998"


def run(cmd: list[str], *, timeout: int = 120, capture: bool = True, env: dict | None = None) -> dict:
    try:
        proc = subprocess.run(
            cmd,
            text=True,
            capture_output=capture,
            timeout=timeout,
            env=env,
            encoding="utf-8",
            errors="replace",
        )
        return {"ok": proc.returncode == 0, "stdout": proc.stdout or "", "stderr": proc.stderr or ""}
    except FileNotFoundError:
        return {"ok": False, "stdout": "", "stderr": f"command not found: {cmd[0]}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": f"timeout after {timeout}s"}


def docker_ready() -> bool:
    return run(["docker", "info"], timeout=30)["ok"]


def network_exists(name: str) -> bool:
    result = run(["docker", "network", "ls", "--format", "{{.Name}}"], timeout=30)
    return name in result["stdout"].split()


def container_running(name: str) -> bool:
    result = run(["docker", "ps", "--filter", f"name=^{name}$", "--format", "{{.Names}}"], timeout=30)
    return name in result["stdout"].splitlines()


def http_json(url: str, *, method: str = "GET", timeout: int = 10) -> dict | None:
    try:
        req = request.Request(url, data=b"{}" if method == "POST" else None, method=method)
        req.add_header("Content-Type", "application/json")
        with request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except Exception:
        return None


def ensure_services_network() -> bool:
    if network_exists(SERVICES_NETWORK):
        print(f"[OK] network exists: {SERVICES_NETWORK}")
        return True
    result = run(["docker", "network", "create", SERVICES_NETWORK], timeout=30)
    print("[OK] created services network" if result["ok"] else f"[FAIL] {result['stderr']}")
    return result["ok"]


def start_service_manager() -> bool:
    if not SERVICES_COMPOSE.exists():
        print(f"[FAIL] missing {SERVICES_COMPOSE.relative_to(REPO_ROOT)}")
        return False
    env = os.environ.copy()
    env.setdefault("HOST_PROJECT_ROOT", str(REPO_ROOT))
    result = run(
        ["docker", "compose", "-f", str(SERVICES_COMPOSE), "up", "-d", "--build"],
        timeout=300,
        capture=False,
        env=env,
    )
    if not result["ok"]:
        print("[FAIL] service-manager compose failed")
        return False
    deadline = time.time() + 60
    while time.time() < deadline:
        status = http_json(f"{SERVICE_MANAGER_URL}/api/status")
        if status and container_running("bench-mailpit"):
            print("[OK] service-manager and Mailpit are ready")
            return True
        time.sleep(2)
    print("[FAIL] service-manager did not become ready")
    return False


def start_gitlab(skip: bool) -> bool:
    if skip:
        print("[SKIP] GitLab startup")
        return True
    http_json(f"{SERVICE_MANAGER_URL}/api/up-gitlab", method="POST", timeout=60)
    deadline = time.time() + 900
    while time.time() < deadline:
        health = http_json(f"{SERVICE_MANAGER_URL}/api/healthcheck/gitlab", timeout=10)
        if health and health.get("healthy"):
            print("[OK] GitLab is healthy")
            return True
        time.sleep(10)
    print("[FAIL] GitLab did not become healthy within 15 minutes")
    return False


def seed_gitlab(skip: bool) -> bool:
    if skip:
        print("[SKIP] GitLab template seed")
        return True
    result = http_json(f"{SERVICE_MANAGER_URL}/api/gitlab/seed-template", method="POST", timeout=180)
    if result and result.get("template_project"):
        print(f"[OK] GitLab template seeded: {result['template_project']}")
        return True
    print("[FAIL] GitLab template seed failed")
    return False


def start_sandbox() -> bool:
    if not SANDBOX_COMPOSE.exists():
        print(f"[FAIL] missing {SANDBOX_COMPOSE.relative_to(REPO_ROOT)}")
        return False
    result = run(
        ["docker", "compose", "-p", "agent-sandbox", "-f", str(SANDBOX_COMPOSE), "up", "-d"],
        timeout=180,
        capture=False,
    )
    if result["ok"]:
        print("[OK] sandbox target-agent is ready")
    else:
        print("[FAIL] sandbox compose failed")
    return result["ok"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare reusable Docker infra for AgentSandboxEval.")
    parser.add_argument("--skip-gitlab", action="store_true", help="Only start service-manager/Mailpit and sandbox.")
    args = parser.parse_args()

    if not docker_ready():
        print("[FAIL] Docker daemon is not running")
        return 1

    checks = [
        ensure_services_network(),
        start_service_manager(),
        start_gitlab(args.skip_gitlab),
        seed_gitlab(args.skip_gitlab),
        start_sandbox(),
    ]
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
