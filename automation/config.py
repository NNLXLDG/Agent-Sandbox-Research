import os
import pathlib

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

RAW_CASES_DIR = PROJECT_ROOT / "Raw_cases"
REPORTS_DIR = PROJECT_ROOT / "reports"
COMPOSE_FILE = PROJECT_ROOT / "docker-compose.yaml"

AGENT_BASE_URL = os.environ.get("AGENT_BASE_URL", "http://127.0.0.1:18789")
AGENT_API_TOKEN = os.environ.get(
    "AGENT_API_TOKEN",
    "f6b70ea09f74497051ac17c96c10f791bad74033ce3c9648",
)
AGENT_MESSAGE_ENDPOINT = "/v1/chat/completions"

API_TIMEOUT = int(os.environ.get("API_TIMEOUT", "120"))
SANDBOX_READY_TIMEOUT = int(os.environ.get("SANDBOX_READY_TIMEOUT", "60"))
SANDBOX_READY_POLL_INTERVAL = 2

CONTAINER_NAME = "agent_eval_sandbox"
