from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from sandbox_eval.case_loader import load_cases
from sandbox_eval.llm_judge import LLMJudge
from sandbox_eval.models import CaseRun
from sandbox_eval.reporter import write_case_artifacts, write_summary
from sandbox_eval.targets import AgentCliTarget, AgentInfraTarget, Target

DEFAULT_ENV_FILE = Path(".secrets/relay/relay.env")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Agent sandbox security evaluation cases")
    parser.add_argument("--cases", type=Path, default=Path("cases"), help="Case root directory")
    parser.add_argument("--report-dir", type=Path, default=Path("reports/demo"), help="Output directory")
    parser.add_argument(
        "-c",
        "--case",
        dest="case_id",
        action="append",
        default=[],
        help="Run selected case IDs. Repeat or use comma-separated values.",
    )
    parser.add_argument(
        "-s",
        "--surface",
        dest="attack_surface",
        action="append",
        default=[],
        help="Run selected attack surfaces. Repeat or use comma-separated values.",
    )
    parser.add_argument(
        "-a",
        "--agent",
        dest="agent_framework",
        choices=["hermes", "openclaw"],
        required=True,
        help="Target Agent framework.",
    )
    parser.add_argument(
        "-llm",
        "--model",
        dest="agent_model",
        default=os.getenv("AGENT_LLM_MODEL", ""),
        help="Agent model. Judge model defaults to the same value.",
    )
    parser.add_argument(
        "--hermes-cmd",
        dest="hermes_command",
        default="",
        help="Override Hermes command. Defaults to HERMES_AGENT_COMMAND or 'hermes run --model {model}'.",
    )
    parser.add_argument(
        "--openclaw-cmd",
        dest="openclaw_command",
        default="",
        help=(
            "Override OpenClaw command. Defaults to OPENCLAW_AGENT_COMMAND "
            "or 'openclaw run --model {model}'."
        ),
    )
    parser.add_argument(
        "--target-mode",
        choices=["infra", "cli"],
        default="infra",
        help="infra uses restored Docker/GitLab adapter infra; cli runs a local command directly.",
    )
    parser.add_argument("--timeout", type=int, default=180, help="Per-case target timeout")
    parser.add_argument("--keep-container", action="store_true", help="Keep infra containers after each case")
    parser.add_argument("--keep-report-dir", action="store_true", help="Do not clean report-dir before run")
    parser.add_argument(
        "--defense-profile",
        choices=["none", "openclaw-prompt-hardening"],
        default="none",
        help="Prompt-level defense profile. Default keeps the original baseline behavior.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _load_env_file(DEFAULT_ENV_FILE)
    args = build_parser().parse_args(argv)
    run_started_at = _timestamp()
    if args.report_dir.exists() and not args.keep_report_dir:
        shutil.rmtree(args.report_dir)
    args.report_dir.mkdir(parents=True, exist_ok=True)

    case_ids = _split_filter_values(args.case_id)
    attack_surfaces = _split_filter_values(args.attack_surface)
    cases = _filter_cases(load_cases(args.cases), case_ids=case_ids, attack_surfaces=attack_surfaces)
    if not cases:
        raise RuntimeError("No cases matched the requested filters.")

    agent_model = _resolve_model_alias(args.agent_model)
    target_command = _resolve_agent_command(
        framework=args.agent_framework,
        hermes_command=args.hermes_command,
        openclaw_command=args.openclaw_command,
    )
    target = _build_target(
        agent_framework=args.agent_framework,
        agent_model=agent_model,
        command=target_command,
        timeout=args.timeout,
        target_mode=args.target_mode,
        keep_container=args.keep_container,
        defense_profile=args.defense_profile,
    )
    judge = LLMJudge(
        model=os.getenv("EVAL_LLM_MODEL", "") or agent_model,
        timeout=args.timeout,
    )

    _log(
        f"start framework={args.agent_framework} model={agent_model or 'unspecified'} "
        f"cases={len(cases)} report_dir={args.report_dir}"
    )
    case_runs: list[CaseRun] = []
    for case in cases:
        _log(f"case_start {case.case_id} {case.attack_surface}")
        run_dir = args.report_dir / "runs" / case.case_id
        target_result = target.run(case, run_dir)
        if target_result.infrastructure_error:
            _write_infrastructure_failure(case, target_result, run_dir)
            _log(f"INFRA_ERROR {case.case_id} {target_result.infrastructure_error}")
            raise RuntimeError(
                f"Agent infrastructure error in {case.case_id}: {target_result.infrastructure_error}"
            )
        verdict = judge.evaluate(case, target_result, run_dir)
        case_run = CaseRun(case=case, target_result=target_result, verdict=verdict, run_dir=run_dir)
        write_case_artifacts(case_run)
        case_runs.append(case_run)
        status = "PASS" if verdict.passed else "FAIL"
        _log(f"{status} {case.case_id} {case.attack_surface}")

    summary = write_summary(
        case_runs,
        args.report_dir,
        metadata={
            "run_started_at": run_started_at,
            "run_finished_at": _timestamp(),
            "agent_framework": args.agent_framework,
            "agent_model": agent_model,
            "target_mode": args.target_mode,
            "defense_profile": args.defense_profile,
            "target_command": target_command if args.target_mode == "cli" else "evaluation.adapters",
            "judge_model": judge.model,
            "case_filters": {
                "case_id": sorted(case_ids),
                "attack_surface": sorted(attack_surfaces),
            },
        },
    )
    _log(f"summary {args.report_dir / 'summary.json'}")
    _log(f"report {args.report_dir / 'report.md'}")
    return 1 if summary["totals"]["failed"] else 0


def _build_target(
    agent_framework: str,
    agent_model: str,
    command: str,
    timeout: int,
    target_mode: str = "infra",
    keep_container: bool = False,
    defense_profile: str = "none",
) -> Target:
    if target_mode == "infra":
        return AgentInfraTarget(
            framework=agent_framework,
            model=agent_model,
            timeout=timeout,
            keep_container=keep_container,
            defense_profile=defense_profile,
        )
    return AgentCliTarget(command, timeout=timeout, framework=agent_framework, model=agent_model)


def _resolve_agent_command(framework: str, hermes_command: str, openclaw_command: str) -> str:
    if framework == "hermes":
        return hermes_command.strip() or os.getenv("HERMES_AGENT_COMMAND", "").strip() or "hermes run --model {model}"
    if framework == "openclaw":
        return (
            openclaw_command.strip()
            or os.getenv("OPENCLAW_AGENT_COMMAND", "").strip()
            or "openclaw run --model {model}"
        )
    raise RuntimeError(f"Unsupported agent framework: {framework}")


def _split_filter_values(values: list[str]) -> set[str]:
    result: set[str] = set()
    for value in values:
        result.update(item.strip() for item in value.split(",") if item.strip())
    return result


def _resolve_model_alias(value: str) -> str:
    model = (value or "").strip()
    if not model:
        return os.getenv("AGENT_LLM_MODEL", "") or os.getenv("DEEPSEEK_MODEL", "")
    aliases = {
        "deepseek": os.getenv("DEEPSEEK_MODEL", ""),
        "chatgpt": os.getenv("CHATGPT_MODEL", ""),
        "gpt": os.getenv("CHATGPT_MODEL", ""),
        "gemini": os.getenv("GEMINI_MODEL", ""),
        "mimo": os.getenv("MIMO_MODEL", ""),
    }
    return aliases.get(model, "") or model


def _filter_cases(cases, *, case_ids: set[str], attack_surfaces: set[str]):
    filtered = cases
    if case_ids:
        known = {case.case_id for case in cases}
        missing = sorted(case_ids - known)
        if missing:
            raise RuntimeError(f"Unknown case_id values: {', '.join(missing)}")
        filtered = [case for case in filtered if case.case_id in case_ids]
    if attack_surfaces:
        known = {case.attack_surface for case in cases}
        missing = sorted(attack_surfaces - known)
        if missing:
            raise RuntimeError(f"Unknown attack_surface values: {', '.join(missing)}")
        filtered = [case for case in filtered if case.attack_surface in attack_surfaces]
    return filtered


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _write_infrastructure_failure(case, target_result, run_dir: Path) -> None:
    import json

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "prompt.txt").write_text(case.payload, encoding="utf-8")
    (run_dir / "assistant.txt").write_text(target_result.response, encoding="utf-8")
    (run_dir / "stdout.log").write_text(target_result.stdout, encoding="utf-8")
    (run_dir / "stderr.log").write_text(target_result.stderr, encoding="utf-8")
    existing_container_log = run_dir / "container.log"
    previous = existing_container_log.read_text(encoding="utf-8") if existing_container_log.exists() else ""
    existing_container_log.write_text(
        (previous.rstrip() + "\n\n" if previous.strip() else "")
        + "# infrastructure failure\n"
        + target_result.container_log
        + f"infrastructure_error={target_result.infrastructure_error}\n",
        encoding="utf-8",
    )
    (run_dir / "infrastructure_error.json").write_text(
        json.dumps(
            {
                "case_id": case.case_id,
                "error": target_result.infrastructure_error,
                "returncode": target_result.returncode,
                "command": target_result.command,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _timestamp() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _log(message: str) -> None:
    print(f"[{_timestamp()}] {message}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
