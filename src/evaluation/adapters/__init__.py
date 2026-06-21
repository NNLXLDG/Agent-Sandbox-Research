"""Agent adapters: contract + Hermes / OpenClaw implementations."""

from evaluation.adapters.base import AgentAdapter, ContainerHandle, WorkspaceContext
from evaluation.adapters.hermes import HermesAdapter
from evaluation.adapters.openclaw import OpenClawAdapter
from evaluation.adapters.registry import AdapterRegistry, default_registry

__all__ = [
    "AgentAdapter",
    "ContainerHandle",
    "WorkspaceContext",
    "HermesAdapter",
    "OpenClawAdapter",
    "AdapterRegistry",
    "default_registry",
]
