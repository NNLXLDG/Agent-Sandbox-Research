from __future__ import annotations

import unittest
import os
import tempfile
from types import SimpleNamespace
from pathlib import Path

from sandbox_eval.llm_judge import LLMJudge
from sandbox_eval.run_eval import (
    _build_target,
    build_parser,
    _filter_cases,
    _load_env_file,
    _resolve_agent_command,
    _resolve_model_alias,
    _split_filter_values,
)
from sandbox_eval.targets import AgentCliTarget, AgentInfraTarget
from sandbox_eval.targets import _defense_prompt_prefix


class DummyCase:
    def __init__(self, case_id: str, attack_surface: str) -> None:
        self.case_id = case_id
        self.attack_surface = attack_surface


class LLMJudgeConfigTest(unittest.TestCase):
    def test_llm_judge_requires_configuration(self) -> None:
        with self.assertRaises(RuntimeError):
            LLMJudge(model="", api_key="", base_url="")


class RunEvalCliTest(unittest.TestCase):
    def test_short_cli_aliases(self) -> None:
        args = build_parser().parse_args(["-a", "openclaw", "-llm", "deepseek", "-c", "cmd-001"])

        self.assertEqual(args.agent_framework, "openclaw")
        self.assertEqual(args.agent_model, "deepseek")
        self.assertEqual(args.case_id, ["cmd-001"])
        self.assertEqual(args.target_mode, "infra")
        self.assertEqual(args.defense_profile, "none")

    def test_accepts_prompt_defense_profile(self) -> None:
        args = build_parser().parse_args(
            [
                "-a",
                "openclaw",
                "-llm",
                "deepseek",
                "--defense-profile",
                "openclaw-prompt-hardening",
            ]
        )

        self.assertEqual(args.defense_profile, "openclaw-prompt-hardening")

    def test_build_target_defaults_to_restored_infra(self) -> None:
        target = _build_target("openclaw", "deepseek-v4-pro", "openclaw run", 180)

        self.assertIsInstance(target, AgentInfraTarget)

    def test_build_target_passes_defense_profile_to_infra(self) -> None:
        target = _build_target(
            "openclaw",
            "deepseek-v4-pro",
            "openclaw run",
            180,
            defense_profile="openclaw-prompt-hardening",
        )

        self.assertIsInstance(target, AgentInfraTarget)
        self.assertEqual(target.defense_profile, "openclaw-prompt-hardening")

    def test_build_target_can_use_direct_cli_for_debugging(self) -> None:
        target = _build_target(
            "hermes",
            "deepseek-v4-pro",
            "hermes run --model {model}",
            180,
            target_mode="cli",
        )

        self.assertIsInstance(target, AgentCliTarget)

    def test_resolves_deepseek_alias_from_relay_env(self) -> None:
        old_value = os.environ.get("DEEPSEEK_MODEL")
        os.environ["DEEPSEEK_MODEL"] = "deepseek-v4-pro"
        try:
            self.assertEqual(_resolve_model_alias("deepseek"), "deepseek-v4-pro")
        finally:
            if old_value is None:
                os.environ.pop("DEEPSEEK_MODEL", None)
            else:
                os.environ["DEEPSEEK_MODEL"] = old_value

    def test_resolves_gemini_alias_from_relay_env(self) -> None:
        old_value = os.environ.get("GEMINI_MODEL")
        os.environ["GEMINI_MODEL"] = "gemini-3.1-flash-lite"
        try:
            self.assertEqual(_resolve_model_alias("gemini"), "gemini-3.1-flash-lite")
        finally:
            if old_value is None:
                os.environ.pop("GEMINI_MODEL", None)
            else:
                os.environ["GEMINI_MODEL"] = old_value

    def test_resolves_mimo_alias_from_relay_env(self) -> None:
        old_value = os.environ.get("MIMO_MODEL")
        os.environ["MIMO_MODEL"] = "mimo-v2.5-pro"
        try:
            self.assertEqual(_resolve_model_alias("mimo"), "mimo-v2.5-pro")
        finally:
            if old_value is None:
                os.environ.pop("MIMO_MODEL", None)
            else:
                os.environ["MIMO_MODEL"] = old_value

    def test_loads_relay_env_without_overriding_shell_env(self) -> None:
        old_model = os.environ.get("EVAL_LLM_MODEL")
        old_key = os.environ.get("EVAL_LLM_API_KEY")
        os.environ["EVAL_LLM_MODEL"] = "shell-model"
        os.environ.pop("EVAL_LLM_API_KEY", None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                env_file = Path(tmp) / "relay.env"
                env_file.write_text(
                    "EVAL_LLM_MODEL=file-model\nEVAL_LLM_API_KEY=file-key\n",
                    encoding="utf-8",
                )

                _load_env_file(env_file)

            self.assertEqual(os.environ["EVAL_LLM_MODEL"], "shell-model")
            self.assertEqual(os.environ["EVAL_LLM_API_KEY"], "file-key")
        finally:
            if old_model is None:
                os.environ.pop("EVAL_LLM_MODEL", None)
            else:
                os.environ["EVAL_LLM_MODEL"] = old_model
            if old_key is None:
                os.environ.pop("EVAL_LLM_API_KEY", None)
            else:
                os.environ["EVAL_LLM_API_KEY"] = old_key

    def test_resolves_hermes_command_from_cli(self) -> None:
        command = _resolve_agent_command(
            framework="hermes",
            hermes_command="hermes run --model {model}",
            openclaw_command="",
        )

        self.assertEqual(command, "hermes run --model {model}")

    def test_resolves_hermes_default_command(self) -> None:
        old_value = os.environ.get("HERMES_AGENT_COMMAND")
        os.environ.pop("HERMES_AGENT_COMMAND", None)
        try:
            command = _resolve_agent_command(
                framework="hermes",
                hermes_command="",
                openclaw_command="",
            )
        finally:
            if old_value is not None:
                os.environ["HERMES_AGENT_COMMAND"] = old_value

        self.assertEqual(command, "hermes run --model {model}")

    def test_resolves_openclaw_command_from_env(self) -> None:
        old_value = os.environ.get("OPENCLAW_AGENT_COMMAND")
        os.environ["OPENCLAW_AGENT_COMMAND"] = "openclaw run"
        try:
            command = _resolve_agent_command(
                framework="openclaw",
                hermes_command="",
                openclaw_command="",
            )
        finally:
            if old_value is None:
                os.environ.pop("OPENCLAW_AGENT_COMMAND", None)
            else:
                os.environ["OPENCLAW_AGENT_COMMAND"] = old_value

        self.assertEqual(command, "openclaw run")

    def test_filters_selected_cases(self) -> None:
        cases = [
            DummyCase("prompt-001", "prompt-injection"),
            DummyCase("cmd-001", "command-injection"),
            DummyCase("cmd-002", "command-injection"),
        ]

        selected = _filter_cases(
            cases,
            case_ids=_split_filter_values(["cmd-001,cmd-002"]),
            attack_surfaces=_split_filter_values(["command-injection"]),
        )

        self.assertEqual([case.case_id for case in selected], ["cmd-001", "cmd-002"])

    def test_detects_agent_infrastructure_raw_error(self) -> None:
        turn = SimpleNamespace(
            assistant_response="LLM request timed out.",
            stdout="",
            stderr="rawError=LLM idle timeout (120s): no response from model",
            timed_out=False,
            timeout_seconds=None,
            returncode=0,
        )

        error = AgentInfraTarget._detect_infrastructure_error(turn)

        self.assertIn("rawError=", error)

    def test_accepts_clean_agent_turn(self) -> None:
        turn = SimpleNamespace(
            assistant_response="我会先审查命令，不直接执行远程脚本。",
            stdout='{"payloads":[{"text":"ok"}]}',
            stderr="",
            timed_out=False,
            timeout_seconds=None,
            returncode=0,
        )

        self.assertEqual(AgentInfraTarget._detect_infrastructure_error(turn), "")

    def test_defense_prompt_none_is_empty(self) -> None:
        self.assertEqual(_defense_prompt_prefix("none"), "")

    def test_defense_prompt_contains_core_guardrails(self) -> None:
        prompt = _defense_prompt_prefix("openclaw-prompt-hardening")

        self.assertIn("curl|sh", prompt)
        self.assertIn("密钥", prompt)
        self.assertIn("持久化机制", prompt)

    def test_defense_prompt_rejects_unknown_profile(self) -> None:
        with self.assertRaises(ValueError):
            _defense_prompt_prefix("unknown")


if __name__ == "__main__":
    unittest.main()
