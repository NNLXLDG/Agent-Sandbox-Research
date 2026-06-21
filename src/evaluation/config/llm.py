"""LLM backend configuration for agent adapter runs."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class LLMBackendConfig:
    """Portable LLM backend descriptor.

    Represents one LLM backend in the evaluation matrix. The relay proxy
    normalises all providers behind an OpenAI-compatible /v1 endpoint, so the
    agent only needs model + api_key + base_url regardless of actual provider.
    """

    label: str                                        # short id, e.g. "deepseek-v4-pro"
    model: str                                        # model name passed to the API
    provider: str = "custom"                          # openai | anthropic | custom
    api_key: str = ""
    base_url: str = "http://llm-relay:4000/v1"
    max_turns: int = 32
    extra_env: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_relay_env(
        cls,
        label: Optional[str] = None,
        *,
        env_file: Optional[Path] = None,
    ) -> "LLMBackendConfig":
        """Build from the project's .secrets/relay/relay.env."""
        from evaluation.config.relay import RelayConfig

        relay = RelayConfig(env_file=env_file)
        env = relay.load_env()
        model = env.get("DEEPSEEK_MODEL", "deepseek-v4-pro").strip() or "deepseek-v4-pro"
        token = (env.get("LLM_RELAY_TOKEN") or "").strip()
        return cls(
            label=label or model,
            model=model,
            api_key=token,
            base_url="http://llm-relay:4000/v1",
            provider="custom",
        )


# ---------------------------------------------------------------------------
# Predefined LLM backends — extend as you add more models
# ---------------------------------------------------------------------------

def default_llm_backends() -> list[LLMBackendConfig]:
    """Return the default set of LLM backends for evaluation.

    Reads from relay env so a single .secrets file drives all backends.
    Extend this list with additional models as needed.
    """
    from evaluation.config.relay import RelayConfig

    relay = RelayConfig()
    env = relay.load_env()
    token = (env.get("LLM_RELAY_TOKEN") or "").strip()
    base = "http://llm-relay:4000/v1"

    backends: list[LLMBackendConfig] = []

    # DeepSeek (primary)
    ds_model = env.get("DEEPSEEK_MODEL", "deepseek-v4-pro").strip() or "deepseek-v4-pro"
    backends.append(LLMBackendConfig(
        label=ds_model,
        model=ds_model,
        api_key=token,
        base_url=base,
    ))

    # Claude (if configured)
    claude_key = (env.get("ANTHROPIC_API_KEY") or "").strip()
    claude_model = env.get("CLAUDE_MODEL", "claude-sonnet-4-6").strip()
    if claude_key:
        backends.append(LLMBackendConfig(
            label=claude_model,
            model=claude_model,
            api_key=claude_key,
            base_url=base,
        ))

    # GPT (if configured)
    chatgpt_key = (env.get("CHATGPT_API_KEY") or env.get("OPENAI_API_KEY") or "").strip()
    chatgpt_model = env.get("CHATGPT_MODEL", env.get("GPT_MODEL", "gpt-4o")).strip()
    if chatgpt_key:
        backends.append(LLMBackendConfig(
            label=chatgpt_model,
            model=chatgpt_model,
            api_key=chatgpt_key,
            base_url=base,
        ))

    if not backends:
        # Fallback: at least one backend from relay defaults
        backends.append(LLMBackendConfig.from_relay_env("deepseek-v4-pro"))

    return backends
