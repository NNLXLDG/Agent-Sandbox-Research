from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from sandbox_eval.models import CaseRun


def write_case_artifacts(case_run: CaseRun) -> None:
    case_run.run_dir.mkdir(parents=True, exist_ok=True)
    effective_prompt_path = case_run.run_dir / "effective_prompt.txt"
    effective_prompt = (
        effective_prompt_path.read_text(encoding="utf-8")
        if effective_prompt_path.exists()
        else case_run.case.payload
    )
    (case_run.run_dir / "prompt.txt").write_text(case_run.case.payload, encoding="utf-8")
    (case_run.run_dir / "assistant.txt").write_text(case_run.target_result.response, encoding="utf-8")
    (case_run.run_dir / "stdout.log").write_text(case_run.target_result.stdout, encoding="utf-8")
    (case_run.run_dir / "stderr.log").write_text(case_run.target_result.stderr, encoding="utf-8")
    existing_container_log = case_run.run_dir / "container.log"
    if existing_container_log.exists():
        previous = existing_container_log.read_text(encoding="utf-8")
        existing_container_log.write_text(
            previous.rstrip() + "\n\n# target result\n" + case_run.target_result.container_log,
            encoding="utf-8",
        )
    else:
        existing_container_log.write_text(case_run.target_result.container_log, encoding="utf-8")
    (case_run.run_dir / "conversation.json").write_text(
        json.dumps(
            {
                "case_id": case_run.case.case_id,
                "prompt": case_run.case.payload,
                "effective_prompt": effective_prompt,
                "assistant_response": case_run.target_result.response,
                "command": case_run.target_result.command,
                "returncode": case_run.target_result.returncode,
                "verdict": asdict(case_run.verdict),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def write_summary(case_runs: list[CaseRun], report_dir: Path, metadata: dict | None = None) -> dict:
    report_dir.mkdir(parents=True, exist_ok=True)
    total = len(case_runs)
    passed = sum(1 for run in case_runs if run.verdict.passed)
    by_surface = Counter(run.case.attack_surface for run in case_runs)
    failed_by_surface = Counter(
        run.case.attack_surface for run in case_runs if not run.verdict.passed
    )
    summary = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "totals": {
            "cases": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": round(passed / total, 4) if total else 1.0,
        },
        "metadata": metadata or {},
        "attack_surfaces": {
            surface: {
                "cases": count,
                "failed": failed_by_surface.get(surface, 0),
            }
            for surface, count in sorted(by_surface.items())
        },
        "results": [
            {
                "case_id": run.case.case_id,
                "title": run.case.title,
                "attack_surface": run.case.attack_surface,
                "scenario": run.case.scenario,
                "attack_vector": run.case.attack_vector,
                "severity": run.case.severity,
                "passed": run.verdict.passed,
                "attack_triggered": run.verdict.attack_triggered,
                "reasons": run.verdict.reasons,
                "judge_mode": run.verdict.judge_mode,
                "checkpoint_results": run.verdict.checkpoint_results,
                "run_dir": str(run.run_dir),
            }
            for run in case_runs
        ],
    }
    (report_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (report_dir / "report.md").write_text(_markdown_report(summary), encoding="utf-8")
    return summary


def _markdown_report(summary: dict) -> str:
    totals = summary["totals"]
    lines = [
        "# Agent Sandbox Security Report",
        "",
        f"- Cases: {totals['cases']}",
        f"- Passed: {totals['passed']}",
        f"- Failed: {totals['failed']}",
        f"- Pass rate: {totals['pass_rate']:.1%}",
    ]
    metadata = summary.get("metadata") or {}
    if metadata:
        lines.extend(
            [
                f"- Agent framework: {metadata.get('agent_framework', 'unknown')}",
                f"- Agent model: {metadata.get('agent_model') or 'unspecified'}",
                f"- Judge model: {metadata.get('judge_model') or 'unspecified'}",
                f"- Defense profile: {metadata.get('defense_profile') or 'none'}",
            ]
        )
    lines.extend(
        [
            "",
            "## Attack Surface Distribution",
            "",
            "| Attack surface | Cases | Failed |",
            "|---|---:|---:|",
        ]
    )
    for surface, item in summary["attack_surfaces"].items():
        lines.append(f"| {surface} | {item['cases']} | {item['failed']} |")
    lines.extend(["", "## Case Results", "", "| Case | Surface | Status | Reason |", "|---|---|---|---|"])
    for result in summary["results"]:
        status = "PASS" if result["passed"] else "FAIL"
        reason = "; ".join(result["reasons"])
        lines.append(
            f"| {result['case_id']} | {result['attack_surface']} / {result['attack_vector']} | {status} | {reason} |"
        )
    lines.append("")
    return "\n".join(lines)
