from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Checkpoint:
    id: str
    stage: str
    question: str
    pass_condition: str
    fail_condition: str
    evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Case:
    case_id: str
    title: str
    attack_surface: str
    scenario: str
    attack_vector: str
    severity: str
    payload: str
    expected_safe_behavior: str
    expected_dangerous_behavior: str
    artifact_refs: list[str]
    checkpoints: list[Checkpoint]
    evidence: list[str]
    case_dir: Path
    prompt_path: Path


@dataclass
class TargetResult:
    response: str
    stdout: str = ""
    stderr: str = ""
    command: list[str] = field(default_factory=list)
    returncode: int = 0
    container_log: str = ""
    infrastructure_error: str = ""


@dataclass
class EvalVerdict:
    case_id: str
    passed: bool
    attack_triggered: bool
    reasons: list[str]
    checkpoint_results: list[dict] = field(default_factory=list)
    judge_mode: str = "llm"


@dataclass
class CaseRun:
    case: Case
    target_result: TargetResult
    verdict: EvalVerdict
    run_dir: Path
