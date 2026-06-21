"""Adapter contract.

V1 had a class hierarchy where each adapter re-implemented Docker / GitLab
plumbing. V2 moves all plumbing to the infra layer and lets adapters focus on
agent-specific shell invocations.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from evaluation.config.settings import AdapterConfig
from evaluation.task.models import Round, SetupResult, Task, TurnResult


@dataclass
class ContainerHandle:
    """Lightweight handle returned by ``start()``.

    Adapters can stash arbitrary internal state in ``meta`` without exposing
    it through the public API.
    """

    name: str
    image: str
    network: str = ""
    extra_networks: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkspaceContext:
    """Returned by ``prepare_workspace()`` to describe what was set up."""

    corpus: dict[str, Any] = field(default_factory=lambda: {"copied": [], "errors": []})
    service_context: Optional[dict[str, Any]] = None
    infra_artifacts: dict[str, Any] = field(default_factory=dict)


class AgentAdapter(ABC):
    """Common contract shared by all agent adapters."""

    name: str = "base"

    def __init__(self, config: AdapterConfig) -> None:
        self.config = config
        self.llm_config: Any = None

    # ---- lifecycle hooks -----------------------------------------------------

    @abstractmethod
    def start(self, container_name: str) -> ContainerHandle: ...

    def prepare_runtime(self, handle: ContainerHandle, task: Task) -> dict:
        """Override to inject model/credentials into the running container."""
        return {"ok": True, "stdout": "", "stderr": "", "command": []}

    @abstractmethod
    def prepare_workspace(self, handle: ContainerHandle, task: Task) -> WorkspaceContext: ...

    def run_setup(self, handle: ContainerHandle, task: Task) -> SetupResult:
        """Optional setup_command.sh execution. Default: no-op."""
        return SetupResult(ok=True)

    @abstractmethod
    def run_round(
        self,
        handle: ContainerHandle,
        task: Task,
        round_data: Round,
        session_id: Optional[str],
    ) -> TurnResult: ...

    @abstractmethod
    def export_artifacts(
        self,
        handle: ContainerHandle,
        task: Task,
        output_dir: Path,
        session_ids: list[str],
    ) -> dict: ...

    @abstractmethod
    def cleanup(
        self,
        handle: ContainerHandle,
        workspace: Optional[WorkspaceContext],
        keep_container: bool = False,
    ) -> dict: ...
