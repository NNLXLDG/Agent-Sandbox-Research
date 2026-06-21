from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "manager" / "manage_services.py"


def load_module():
    spec = importlib.util.spec_from_file_location("manage_services_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class DummyHandler:
    def __init__(self, path: str, payload: dict) -> None:
        self.path = path
        body = json.dumps(payload).encode("utf-8")
        self.headers = {"Content-Length": str(len(body))}
        self.rfile = type("Reader", (), {"read": lambda _self, _n: body})()
        self.responses: list[tuple[int, dict]] = []

    def _send(self, code: int, obj: dict) -> None:
        self.responses.append((code, obj))


class ManageServicesTest(unittest.TestCase):
    def test_safe_run_project_only_accepts_bench_run_projects(self) -> None:
        module = load_module()

        self.assertTrue(module.is_safe_run_project("bench/agent-sandbox-run-001"))
        self.assertTrue(module.is_safe_run_project("bench/prompt-001-run-20260613"))
        self.assertFalse(module.is_safe_run_project("bench/agent-sandbox-template"))
        self.assertFalse(module.is_safe_run_project("bench/project-template"))
        self.assertFalse(module.is_safe_run_project("other/agent-sandbox-run-001"))
        self.assertFalse(module.is_safe_run_project(""))

    def test_delete_run_project_rejects_template_project(self) -> None:
        module = load_module()

        result = module.delete_run_project("bench/agent-sandbox-template")

        self.assertEqual(result, {"status": "skipped_unsafe_name", "project": "bench/agent-sandbox-template"})

    def test_delete_project_endpoint_requires_project_field(self) -> None:
        module = load_module()
        handler = DummyHandler("/api/gitlab/delete-project", {})

        module.Handler.do_POST(handler)

        self.assertEqual(handler.responses, [(400, {"error": "project required"})])

    def test_delete_project_endpoint_calls_delete_helper(self) -> None:
        module = load_module()
        handler = DummyHandler("/api/gitlab/delete-project", {"project": "bench/agent-sandbox-run-001"})
        module.delete_run_project = lambda project: {"status": "deleted", "project": project}

        module.Handler.do_POST(handler)

        self.assertEqual(
            handler.responses,
            [(200, {"status": "deleted", "project": "bench/agent-sandbox-run-001"})],
        )

    def test_status_includes_gitlab_and_mailpit(self) -> None:
        module = load_module()
        module.ensure_dirs = lambda: None
        module.container_exists = lambda name: name in {"bench-gitlab", "bench-mailpit"}
        module.container_running = lambda name: name == "bench-mailpit"

        result = module.status()

        self.assertEqual(result["gitlab_container"], "bench-gitlab")
        self.assertTrue(result["gitlab_exists"])
        self.assertFalse(result["gitlab_running"])
        self.assertEqual(result["mailpit_container"], "bench-mailpit")
        self.assertTrue(result["mailpit_exists"])
        self.assertTrue(result["mailpit_running"])


if __name__ == "__main__":
    unittest.main()
