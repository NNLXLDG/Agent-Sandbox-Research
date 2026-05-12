import subprocess
import time
import sys
import requests

from .config import COMPOSE_FILE, CONTAINER_NAME, AGENT_BASE_URL, AGENT_API_TOKEN, SANDBOX_READY_TIMEOUT, SANDBOX_READY_POLL_INTERVAL

_COMPOSE_CWD = str(COMPOSE_FILE.parent)


def _run_compose(args: list[str], capture: bool = True) -> subprocess.CompletedProcess:
    cmd = ["docker", "compose", "-f", str(COMPOSE_FILE)] + args
    return subprocess.run(cmd, capture_output=capture, text=True, timeout=120, cwd=_COMPOSE_CWD)


def check_running() -> bool:
    result = subprocess.run(
        ["docker", "ps", "--filter", f"name={CONTAINER_NAME}", "--format", "{{.Names}}"],
        capture_output=True, text=True,
    )
    return CONTAINER_NAME in result.stdout


def start_sandbox() -> bool:
    if check_running():
        return True
    print("[sandbox] Starting container...")
    result = _run_compose(["up", "-d", "--wait"], capture=True)
    if result.returncode != 0:
        print(f"[sandbox] ERROR starting container:\n{result.stderr}")
        return False
    return wait_ready()


def stop_sandbox() -> bool:
    if not check_running():
        return True
    print("[sandbox] Stopping container...")
    result = _run_compose(["down"], capture=True)
    if result.returncode != 0:
        print(f"[sandbox] ERROR stopping container:\n{result.stderr}")
        return False
    return True


def restart_sandbox() -> bool:
    print("[sandbox] Restarting sandbox for clean state...")
    stop_sandbox()
    time.sleep(2)
    return start_sandbox()


def wait_ready() -> bool:
    print(f"[sandbox] Waiting for agent to be ready (timeout {SANDBOX_READY_TIMEOUT}s)...")
    deadline = time.time() + SANDBOX_READY_TIMEOUT
    while time.time() < deadline:
        try:
            resp = requests.get(
                f"{AGENT_BASE_URL}/health",
                headers={"Authorization": f"Bearer {AGENT_API_TOKEN}"},
                timeout=5,
            )
            if resp.status_code in (200, 404):
                print("[sandbox] Agent is ready.")
                return True
        except requests.ConnectionError:
            pass
        except Exception:
            pass
        sys.stdout.write(".")
        sys.stdout.flush()
        time.sleep(SANDBOX_READY_POLL_INTERVAL)
    print(f"\n[sandbox] ERROR: Agent did not become ready within {SANDBOX_READY_TIMEOUT}s")
    return False
