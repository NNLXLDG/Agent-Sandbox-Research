"""ArtifactExporter: glue between adapter export hooks and the on-disk layout."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from evaluation.adapters.base import AgentAdapter, ContainerHandle
from evaluation.task.models import Task


class ArtifactExporter:
    """Asks an adapter to copy session/log files out of its container.

    This is a thin wrapper that exists so that:
    * adapters don't need to know the on-disk layout the orchestrator wants
    * the orchestrator gets a consistent return shape regardless of agent
    """

    def export(
        self,
        adapter: AgentAdapter,
        handle: ContainerHandle,
        task: Task,
        runs_dir: Path,
        session_ids: list[str],
    ) -> dict:
        target = runs_dir / "runtime_artifacts"
        target.mkdir(parents=True, exist_ok=True)
        try:
            return adapter.export_artifacts(handle, task, target, session_ids)
        except Exception as exc:  # we never want export failures to mask earlier results
            return {"error": f"export_failed: {exc}", "runtime_artifacts_root": str(target)}
