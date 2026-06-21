"""Relay (LLM proxy) environment loading and validation.

Replaces the duplicated ``load_relay_env`` / ``relay_mode_state`` logic in V1.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from evaluation.config.constants import (
    RELAY_CONFIG_FILE,
    RELAY_ENV_FILE,
)


@dataclass
class RelayState:
    """Whether relay mode is fully usable, and why."""

    enabled: bool
    reason: str
    values: dict = field(default_factory=dict)


class RelayConfig:
    """Reads ``.secrets/relay/relay.env`` and validates relay readiness."""

    def __init__(
        self,
        env_file: Path = RELAY_ENV_FILE,
        config_file: Path = RELAY_CONFIG_FILE,
    ) -> None:
        self.env_file = env_file
        self.config_file = config_file

    def load_env(self) -> dict[str, str]:
        env: dict[str, str] = {}
        if not self.env_file.exists():
            return env
        for raw_line in self.env_file.read_text(encoding="utf-8").splitlines():
            # Strip BOM and whitespace, ignore comments.
            line = raw_line.strip().lstrip("﻿")
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().lstrip("﻿")
        return env

    def state(self) -> RelayState:
        if not self.env_file.exists():
            return RelayState(False, f"missing relay env file: {self.env_file}")

        values = self.load_env()
        # Normalize keys to upper-case for consistent lookup.
        upper = {k.upper(): v for k, v in values.items()}

        api_key = upper.get("OPENROUTER_API_KEY", "")
        relay_token = upper.get("LLM_RELAY_TOKEN", "")
        if not api_key or api_key == "PASTE_YOUR_OPENROUTER_TOKEN_HERE":
            return RelayState(False, "relay env missing usable OPENROUTER_API_KEY", upper)
        if not relay_token:
            return RelayState(False, "relay env missing LLM_RELAY_TOKEN", upper)
        if not self.config_file.exists():
            return RelayState(False, f"missing relay config file: {self.config_file}", upper)
        return RelayState(True, "relay configured", upper)

    @property
    def relay_token(self) -> str:
        return self.load_env().get("LLM_RELAY_TOKEN", "").strip()

    @property
    def deepseek_model(self) -> str:
        return self.load_env().get("DEEPSEEK_MODEL", "deepseek-v4-pro").strip() or "deepseek-v4-pro"
