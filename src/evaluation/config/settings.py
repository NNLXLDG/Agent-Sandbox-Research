"""Configuration dataclasses replacing scattered argparse.Namespace usage."""
from __future__ import annotations

from dataclasses import dataclass, field
from evaluation.config.constants import (
    HERMES_DEFAULT_TIMEOUT,
    HERMES_IMAGE,
    HERMES_WORKSPACE_ROOT,
    OPENCLAW_DEFAULT_TIMEOUT,
    OPENCLAW_IMAGE,
    OPENCLAW_WORKSPACE_ROOT,
)


@dataclass
class AdapterConfig:
    """Base configuration shared by all adapters."""

    image: str
    workspace_root: str
    timeout: int
    relay_token: str = ""
    model: str = ""
    provider: str = ""
    extra_env: dict = field(default_factory=dict)


@dataclass
class HermesAdapterConfig(AdapterConfig):
    image: str = HERMES_IMAGE
    workspace_root: str = HERMES_WORKSPACE_ROOT
    timeout: int = HERMES_DEFAULT_TIMEOUT
    max_turns: int = 32


@dataclass
class OpenClawAdapterConfig(AdapterConfig):
    image: str = OPENCLAW_IMAGE
    workspace_root: str = OPENCLAW_WORKSPACE_ROOT
    timeout: int = OPENCLAW_DEFAULT_TIMEOUT
