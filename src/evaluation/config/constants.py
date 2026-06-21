"""Centralized constants. All magic strings, image names, and default paths live here."""
from __future__ import annotations

import os
from pathlib import Path

# Repository roots (resolved relative to this file's location).
# constants.py lives at src/evaluation/config/constants.py → parents[3] = project root
REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = REPO_ROOT / "data"
CASES_ROOT = REPO_ROOT / "cases"
INFRA_ROOT = REPO_ROOT / "infra"
OUTPUT_ROOT = REPO_ROOT / "output"
TASKS_ROOT = CASES_ROOT
TASK_PACKAGES_ROOT = CASES_ROOT

# Container images.
HERMES_IMAGE = os.environ.get("HERMES_IMAGE", "nousresearch/hermes-agent:latest")
OPENCLAW_IMAGE = os.environ.get("OPENCLAW_IMAGE", "alpine/openclaw:main")

# Service endpoints.
SERVICE_MANAGER_URL = os.environ.get("SERVICE_MANAGER_URL", "http://127.0.0.1:2998")
HOST_GITLAB_URL = os.environ.get("HOST_GITLAB_URL", "http://127.0.0.1:8929")

# Relay (LLM) configuration.
RELAY_ENV_FILE = REPO_ROOT / ".secrets" / "relay" / "relay.env"
RELAY_CONFIG_FILE = REPO_ROOT / ".secrets" / "relay" / "config.yaml"
RELAY_NETWORK_NAME = "sandbox_sandbox-net"
SERVICES_NETWORK_NAME = "bench-services-net"

# Hermes runtime defaults.
HERMES_DEFAULT_TIMEOUT = 180
HERMES_WORKSPACE_ROOT = "/opt/data/workspace"
HERMES_RUNTIME_HOME = "/opt/data"
HERMES_BINARY_PATH = "/opt/hermes/.venv/bin/hermes"

# OpenClaw runtime defaults.
OPENCLAW_DEFAULT_TIMEOUT = 420
OPENCLAW_WORKSPACE_ROOT = "/home/node/.openclaw/workspace"

# Default git identity for repo materialization in containers.
DEFAULT_GIT_AUTHOR_NAME = os.environ.get("BENCH_GIT_AUTHOR_NAME", "Bench Runner")
DEFAULT_GIT_AUTHOR_EMAIL = os.environ.get("BENCH_GIT_AUTHOR_EMAIL", "bench-runner@example.com")

# Project templates: shape the in-container workspace and guide agents.
DEFAULT_PROJECT_TEMPLATE = "project"
PROJECT_TEMPLATE_CONTEXT: dict = {
    "project": {
        "project_slug": "project",
        "display_name": "Project",
        "project_type": "GitLab 代码项目",
        "readme_candidates": ["README.md", "SECURITY.md"],
    },
}

# Severity scoring lookup.
SEVERITY_SCORES: dict = {
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}
