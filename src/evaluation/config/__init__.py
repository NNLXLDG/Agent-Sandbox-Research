"""Configuration layer: dataclasses, constants, and environment loading."""

from evaluation.config.constants import (
    HERMES_IMAGE,
    OPENCLAW_IMAGE,
    DEFAULT_PROJECT_TEMPLATE,
    PROJECT_TEMPLATE_CONTEXT,
    DEFAULT_GIT_AUTHOR_NAME,
    DEFAULT_GIT_AUTHOR_EMAIL,
)
from evaluation.config.llm import LLMBackendConfig, default_llm_backends
from evaluation.config.settings import (
    AdapterConfig,
    HermesAdapterConfig,
    OpenClawAdapterConfig,
)
from evaluation.config.relay import RelayConfig, RelayState

__all__ = [
    "HERMES_IMAGE",
    "OPENCLAW_IMAGE",
    "DEFAULT_PROJECT_TEMPLATE",
    "PROJECT_TEMPLATE_CONTEXT",
    "DEFAULT_GIT_AUTHOR_NAME",
    "DEFAULT_GIT_AUTHOR_EMAIL",
    "AdapterConfig",
    "LLMBackendConfig",
    "HermesAdapterConfig",
    "OpenClawAdapterConfig",
    "RelayConfig",
    "RelayState",
    "default_llm_backends",
]
