"""Data models for sandbox case execution through agent adapters."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class AttackMeta:
    layer: str
    stage_coverage: list[str] = field(default_factory=list)
    round_stage_map: dict[str, list[str]] = field(default_factory=dict)
    expected_attack_signal: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AttackMeta":
        stage_coverage = [str(item) for item in (raw.get("stage_coverage") or []) if str(item).strip()]
        round_stage_map: dict[str, list[str]] = {}
        raw_map = raw.get("round_stage_map") or {}
        if isinstance(raw_map, dict):
            for key, value in raw_map.items():
                if isinstance(value, list):
                    round_stage_map[str(key)] = [str(item) for item in value if str(item).strip()]
                elif isinstance(value, str) and value.strip():
                    round_stage_map[str(key)] = [value.strip()]
        return cls(
            layer=str(raw.get("layer", "unknown")),
            stage_coverage=stage_coverage,
            round_stage_map=round_stage_map,
            expected_attack_signal=raw.get("expected_attack_signal"),
            raw=raw,
        )


@dataclass
class TaskMeta:
    id: str
    technique: str = "unknown"
    phase: str = "unknown"
    objective: str = "unknown"
    severity: str = "MEDIUM"
    project_template: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TaskMeta":
        runtime = raw.get("runtime") or {}
        return cls(
            id=str(raw.get("id") or raw.get("case_id") or "unknown"),
            technique=str(raw.get("technique") or raw.get("attack_vector") or "unknown"),
            phase=str(raw.get("phase") or raw.get("attack_surface") or "unknown"),
            objective=str(raw.get("objective") or raw.get("title") or "unknown"),
            severity=str(raw.get("severity") or "MEDIUM").upper(),
            project_template=raw.get("project_template") or runtime.get("project_template") or "project",
            raw=raw,
        )


@dataclass
class Round:
    round: int
    payload: str
    is_malicious: bool = False
    session_break: bool = False
    skip_prefix: bool = False


@dataclass
class Task:
    meta: TaskMeta
    rounds: list[Round]
    instruction: str
    task_dir: Path
    project_context: dict[str, Any] = field(default_factory=dict)
    repo_overlay_dir: Optional[Path] = None
    attack: Optional[AttackMeta] = None
    checkpoints_text: str = ""
    safe_completion_text: str = ""
    verifier_path: Optional[Path] = None
    export_paths: list[str] = field(default_factory=list)

    def primary_payload(self) -> str:
        if self.rounds:
            return self.rounds[0].payload
        return self.instruction

    @property
    def is_attack_variant(self) -> bool:
        return self.attack is not None


@dataclass
class TurnResult:
    turn: int
    query: str
    assistant_response: str
    ok: bool = False
    returncode: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    command: str = ""
    session_id: Optional[str] = None
    is_malicious: bool = False
    session_break: bool = False
    timed_out: bool = False
    timeout_seconds: Optional[int] = None
    raw_payload: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class SetupResult:
    ok: bool
    returncode: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    command: list[str] = field(default_factory=list)
