from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sandbox_eval.models import Case, Checkpoint


def load_cases(root: Path) -> list[Case]:
    case_files = sorted(root.glob("**/case.yaml"))
    cases = [load_case(path) for path in case_files]
    ids = [case.case_id for case in cases]
    duplicates = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
    if duplicates:
        raise ValueError(f"duplicate case_id values: {', '.join(duplicates)}")
    return cases


def load_case(path: Path) -> Case:
    raw = _load_json_subset(path)
    prompt_path = path.parent / "prompt.txt"
    payload = _load_payload(raw, prompt_path)
    expected = raw.get("expected", {})
    checkpoints_raw = raw.get("checkpoints", [])
    if not isinstance(checkpoints_raw, list) or not checkpoints_raw:
        raise ValueError(f"{path} must define a non-empty checkpoints list")
    return Case(
        case_id=_required(raw, "case_id", path) if raw.get("case_id") else _required(raw, "id", path),
        title=_required(raw, "title", path),
        attack_surface=_required(raw, "attack_surface", path),
        scenario=str(raw.get("scenario", "project-maintenance")).strip(),
        attack_vector=str(raw.get("attack_vector", "unknown")).strip(),
        severity=str(raw.get("severity", "MEDIUM")).upper(),
        payload=payload,
        expected_safe_behavior=_required(expected, "safe_behavior", path),
        expected_dangerous_behavior=_required(expected, "dangerous_behavior", path),
        artifact_refs=list(raw.get("artifact_refs", [])),
        checkpoints=[_load_checkpoint(item, path) for item in checkpoints_raw],
        evidence=list(raw.get("evidence", [])),
        case_dir=path.parent,
        prompt_path=prompt_path,
    )


def _load_checkpoint(raw: dict[str, Any], path: Path) -> Checkpoint:
    if not isinstance(raw, dict):
        raise ValueError(f"{path} checkpoint entries must be objects")
    return Checkpoint(
        id=_required(raw, "id", path),
        stage=_required(raw, "stage", path),
        question=_required(raw, "question", path),
        pass_condition=_required(raw, "pass_condition", path),
        fail_condition=_required(raw, "fail_condition", path),
        evidence=list(raw.get("evidence", [])),
    )


def _load_json_subset(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{path} must use the JSON subset of YAML so the demo has no external parser dependency"
        ) from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain an object")
    return data


def _load_payload(raw: dict[str, Any], prompt_path: Path) -> str:
    rounds = (raw.get("interaction") or {}).get("rounds") if isinstance(raw.get("interaction"), dict) else None
    if isinstance(rounds, list) and rounds:
        first = rounds[0]
        if isinstance(first, dict) and isinstance(first.get("payload"), str) and first["payload"].strip():
            return first["payload"].strip()
    return prompt_path.read_text(encoding="utf-8").strip()


def _required(raw: dict[str, Any], key: str, path: Path) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} missing required string field: {key}")
    return value.strip()
