from __future__ import annotations

import json
from pathlib import Path
import unittest

from sandbox_eval.case_loader import load_cases
from evaluation.task.loader import TaskLoader


class CaseLoaderTest(unittest.TestCase):
    def test_all_demo_cases_define_safe_and_dangerous_behavior(self) -> None:
        cases = load_cases(Path("cases"))

        self.assertGreaterEqual(len(cases), 25)
        self.assertEqual(len({case.case_id for case in cases}), len(cases))
        self.assertGreaterEqual(
            {case.attack_surface for case in cases},
            {
                "prompt-injection",
                "data-exfiltration",
                "command-injection",
                "persistence",
                "social-engineering",
            },
        )
        surface_counts = {
            surface: sum(1 for case in cases if case.attack_surface == surface)
            for surface in {case.attack_surface for case in cases}
        }
        self.assertTrue(all(count >= 5 for count in surface_counts.values()))
        for case in cases:
            with self.subTest(case_id=case.case_id):
                self.assertTrue(case.payload)
                self.assertTrue(case.expected_safe_behavior)
                self.assertTrue(case.expected_dangerous_behavior)
                self.assertGreaterEqual(len(case.checkpoints), 1)
                self.assertEqual(
                    len({checkpoint.id for checkpoint in case.checkpoints}),
                    len(case.checkpoints),
                )
                for checkpoint in case.checkpoints:
                    self.assertTrue(checkpoint.stage)
                    self.assertTrue(checkpoint.question)
                    self.assertTrue(checkpoint.pass_condition)
                    self.assertTrue(checkpoint.fail_condition)

    def test_cases_do_not_define_rule_based_judges(self) -> None:
        for case_file in Path("cases").glob("**/case.yaml"):
            with self.subTest(case_file=str(case_file)):
                raw = json.loads(case_file.read_text(encoding="utf-8"))
                self.assertNotIn("judge", raw)
                self.assertNotIn("rules", raw)
                self.assertNotIn("safe_indicators", raw)
                self.assertNotIn("dangerous_indicators", raw)

    def test_cases_are_directly_loadable_by_infra_task_loader(self) -> None:
        loader = TaskLoader(task_packages_root=Path("cases"))
        tasks = [loader._build_task(path) for path in loader.iter_task_dirs()]

        self.assertEqual(len(tasks), 25)
        self.assertEqual({task.task_dir.name for task in tasks}, {task.meta.id for task in tasks})
        for task in tasks:
            with self.subTest(task_id=task.meta.id):
                self.assertEqual(task.meta.raw.get("case_id"), task.meta.id)
                self.assertEqual(task.meta.technique, task.meta.raw.get("attack_vector"))
                self.assertEqual(task.meta.phase, task.meta.raw.get("attack_surface"))
                self.assertEqual(task.meta.project_template, "project")
                self.assertEqual(len(task.rounds), 1)
                self.assertTrue(task.rounds[0].payload)
                self.assertTrue(task.attack)
                self.assertEqual(task.export_paths, ["."])
                self.assertEqual(task.project_context["workspace_dir_name"], "project")
                self.assertEqual(task.repo_overlay_dir, task.task_dir / "environment")

    def test_prompt_injection_contains_direct_attacker_payloads(self) -> None:
        direct_methods = {
            "direct-system-prompt-extraction",
            "direct-authority-impersonation",
            "direct-output-format-hijack",
        }
        found = set()
        for case_file in Path("cases/prompt-injection").glob("*/case.yaml"):
            raw = json.loads(case_file.read_text(encoding="utf-8"))
            attack_vector = str(raw.get("attack_vector", "")).strip()
            if attack_vector in direct_methods:
                found.add(attack_vector)

        self.assertEqual(found, direct_methods)


if __name__ == "__main__":
    unittest.main()
