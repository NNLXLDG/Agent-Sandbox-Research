"""Load sandbox cases as adapter tasks."""
from __future__ import annotations

import json
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover
    yaml = None

from evaluation.config.constants import DEFAULT_PROJECT_TEMPLATE, PROJECT_TEMPLATE_CONTEXT, TASK_PACKAGES_ROOT
from evaluation.task.models import AttackMeta, Round, Task, TaskMeta


class TaskNotFoundError(FileNotFoundError):
    """Raised when a requested case cannot be located on disk."""


class TaskLoader:
    """Loads sandbox case packages from ``cases/**/case.yaml``."""

    def __init__(self, task_packages_root: Path = TASK_PACKAGES_ROOT) -> None:
        self.task_packages_root = task_packages_root

    def iter_task_dirs(self) -> list[Path]:
        return sorted(p.parent for p in self.task_packages_root.glob("*/*/case.yaml"))

    def resolve_task_dir(self, task_id: str) -> Path:
        for task_dir in self.iter_task_dirs():
            raw = _load_structured_file(task_dir / "case.yaml")
            candidate_id = str(raw.get("case_id") or raw.get("id") or task_dir.name).strip()
            if candidate_id == task_id:
                return task_dir
        raise TaskNotFoundError(f"Case not found: {task_id}")

    def load(self, task_id: str) -> Task:
        return self._build_task(self.resolve_task_dir(task_id))

    def _build_task(self, task_dir: Path) -> Task:
        raw = _load_structured_file(task_dir / "case.yaml")
        raw = self._normalize_case(raw, task_dir)

        instruction = self._read_optional(task_dir / "instruction.md") or self._default_sandbox_instruction()
        rounds = self._build_rounds(raw, instruction)
        runtime = raw.get("runtime") or {}
        export_paths = [str(p).strip() for p in (runtime.get("export_paths") or []) if str(p).strip()]
        verifier_path = task_dir / "verify.py"

        return Task(
            meta=TaskMeta.from_dict(raw),
            rounds=rounds,
            instruction=instruction,
            task_dir=task_dir,
            project_context=self._build_project_context(raw),
            repo_overlay_dir=self._resolve_repo_overlay_dir(task_dir, raw),
            attack=self._build_attack_meta(raw),
            checkpoints_text=self._read_optional(task_dir / "checkpoints.md"),
            safe_completion_text=self._read_optional(task_dir / "safe_completion.md"),
            verifier_path=verifier_path if verifier_path.exists() else None,
            export_paths=export_paths,
        )

    @staticmethod
    def _normalize_case(raw: dict, task_dir: Path) -> dict:
        normalized = dict(raw)
        case_id = str(normalized.get("case_id") or normalized.get("id") or task_dir.name).strip()
        normalized.setdefault("case_id", case_id)
        normalized.setdefault("id", case_id)
        normalized.setdefault("technique", normalized.get("attack_vector") or "unknown")
        normalized.setdefault("phase", normalized.get("attack_surface") or "unknown")
        normalized.setdefault("objective", normalized.get("title") or case_id)
        normalized.setdefault("project_template", DEFAULT_PROJECT_TEMPLATE)
        normalized.setdefault(
            "runtime",
            {
                "project_template": normalized["project_template"],
                "export_paths": ["."],
            },
        )
        if not normalized.get("interaction"):
            prompt_path = task_dir / "prompt.txt"
            payload = prompt_path.read_text(encoding="utf-8").strip() if prompt_path.exists() else ""
            normalized["interaction"] = {
                "rounds": [
                    {
                        "round": 1,
                        "payload": payload,
                        "is_malicious": True,
                        "session_break": False,
                    }
                ]
            }
        if not isinstance(normalized.get("attack"), dict):
            expected = normalized.get("expected") or {}
            normalized["attack"] = {
                "layer": normalized.get("attack_surface") or "unknown",
                "expected_attack_signal": expected.get("dangerous_behavior"),
                "method": [normalized.get("attack_vector") or "unknown"],
            }
        return normalized

    @staticmethod
    def _build_rounds(raw: dict, instruction: str) -> list[Round]:
        raw_rounds = raw.get("interaction", {}).get("rounds", []) or []
        rounds = [
            Round(
                round=int(item.get("round", idx + 1)),
                payload=str(item.get("payload", "")).strip(),
                is_malicious=bool(item.get("is_malicious", False)),
                session_break=bool(item.get("session_break", False)),
            )
            for idx, item in enumerate(raw_rounds)
        ]
        return rounds or [Round(round=1, payload=instruction)]

    @staticmethod
    def _build_attack_meta(raw: dict) -> AttackMeta | None:
        attack_raw = raw.get("attack")
        if not isinstance(attack_raw, dict):
            return None
        return AttackMeta.from_dict(attack_raw)

    @staticmethod
    def _build_project_context(raw: dict) -> dict:
        template = str(raw.get("project_template") or DEFAULT_PROJECT_TEMPLATE).strip()
        context = dict(PROJECT_TEMPLATE_CONTEXT.get(template) or {})
        slug = context.get("project_slug") or template
        if not slug:
            raise ValueError("project_template is required")
        context.setdefault("project_slug", slug)
        context.setdefault("display_name", slug)
        context.setdefault("project_type", "GitLab 代码项目")
        context.setdefault("readme_candidates", ["README.md"])
        context["project_template"] = template
        context["workspace_dir_name"] = slug
        return context

    @staticmethod
    def _resolve_repo_overlay_dir(task_dir: Path, raw: dict) -> Path:
        runtime = raw.get("runtime") or {}
        configured = raw.get("repo_overlay") or runtime.get("repo_overlay")
        if configured:
            path = Path(str(configured))
            return path if path.is_absolute() else task_dir / path
        overlay = task_dir / "overlay"
        return overlay if overlay.exists() else task_dir / "environment"

    @staticmethod
    def _read_optional(path: Path) -> str:
        return path.read_text(encoding="utf-8") if path.exists() else ""

    @staticmethod
    def _default_sandbox_instruction() -> str:
        return ""


def _load_structured_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text) if yaml is not None else json.loads(text)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain an object")
    return data
