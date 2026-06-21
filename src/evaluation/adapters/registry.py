"""Adapter registry / factory. Replaces V1's module-level ADAPTERS dict."""
from __future__ import annotations

from typing import Callable, Optional

from evaluation.adapters.base import AgentAdapter
from evaluation.adapters.hermes import HermesAdapter
from evaluation.adapters.openclaw import OpenClawAdapter
from evaluation.config.settings import (
    AdapterConfig,
    HermesAdapterConfig,
    OpenClawAdapterConfig,
)


AdapterFactory = Callable[[Optional[AdapterConfig]], AgentAdapter]


class AdapterRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, AdapterFactory] = {}

    def register(self, name: str, factory: AdapterFactory) -> None:
        self._factories[name] = factory

    def create(self, name: str, config: Optional[AdapterConfig] = None) -> AgentAdapter:
        if name not in self._factories:
            raise KeyError(f"Unknown agent: {name}. Registered: {list(self._factories)}")
        return self._factories[name](config)

    def names(self) -> list[str]:
        return sorted(self._factories.keys())


def _hermes_factory(config: Optional[AdapterConfig]) -> AgentAdapter:
    return HermesAdapter(config or HermesAdapterConfig())


def _openclaw_factory(config: Optional[AdapterConfig]) -> AgentAdapter:
    return OpenClawAdapter(config or OpenClawAdapterConfig())


def default_registry() -> AdapterRegistry:
    registry = AdapterRegistry()
    registry.register("hermes", _hermes_factory)
    registry.register("openclaw", _openclaw_factory)
    return registry
