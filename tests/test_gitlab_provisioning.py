from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path("src/evaluation/infra/provision_gitlab_project.py")


def load_module():
    spec = importlib.util.spec_from_file_location("provision_gitlab_project_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class GitLabProvisioningTest(unittest.TestCase):
    def test_run_project_name_is_unique_per_case_and_executor(self) -> None:
        module = load_module()

        name = module.build_project_name("cmd-001", "openclaw", "project")

        self.assertTrue(name.startswith("project-run-cmd-001-openclaw-"))
        self.assertFalse(name.endswith("-template"))

    def test_default_project_uses_shared_gitlab_template(self) -> None:
        module = load_module()

        self.assertEqual(module.template_project_name("project"), "agent-sandbox-template")

    def test_artifact_refs_are_materialized_at_prompt_paths(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp) / "cmd-001"
            env_dir = case_dir / "environment"
            env_dir.mkdir(parents=True)
            artifact = env_dir / "artifact.txt"
            artifact.write_text("payload", encoding="utf-8")
            meta = {
                "artifact_refs": [str(artifact)],
            }

            file_map = module.build_overlay_file_map(
                case_dir,
                meta,
                env_dir,
                "检查 `sandbox/project/build/failed_command.txt`",
            )

        self.assertEqual(file_map, {"build/failed_command.txt": artifact})

    def test_overlay_directory_files_are_used_when_present(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp) / "prompt-001"
            overlay_dir = case_dir / "overlay"
            overlay_file = overlay_dir / "vendor/acme/CHANGELOG.md"
            overlay_file.parent.mkdir(parents=True)
            overlay_file.write_text("overlay", encoding="utf-8")

            file_map = module.build_overlay_file_map(case_dir, {}, overlay_dir, "")

        self.assertEqual(file_map, {"vendor/acme/CHANGELOG.md": overlay_file})

    def test_gitlab_container_url_is_rewritten_for_host_overlay_push(self) -> None:
        module = load_module()

        url = module.host_reachable_gitlab_url("http://gitlab:8929/bench/project-run-x.git")

        self.assertEqual(url, "http://127.0.0.1:8929/bench/project-run-x.git")

    def test_overlay_uses_helper_token_when_project_response_omits_token(self) -> None:
        module = load_module()
        module.ensure_gitlab_token = lambda: "helper-token"
        original_build = module.build_overlay_file_map
        module.build_overlay_file_map = lambda *_args: {}
        try:
            result = module.apply_case_overlay(
                {"http_url_to_repo": "http://gitlab:8929/bench/project-run-x.git"},
                {"_case_dir": "."},
            )
        finally:
            module.build_overlay_file_map = original_build

        self.assertEqual(result, {"ok": True, "files": [], "commit": None})

    def test_overlay_helper_token_is_returned_for_container_clone(self) -> None:
        module = load_module()
        project = {"http_url_to_repo": "http://gitlab:8929/bench/project-run-x.git"}
        module.ensure_gitlab_token = lambda: "helper-token"
        original_build = module.build_overlay_file_map
        module.build_overlay_file_map = lambda *_args: {}
        try:
            module.apply_case_overlay(project, {"_case_dir": "."})
        finally:
            module.build_overlay_file_map = original_build

        self.assertEqual(project["token"], "helper-token")


if __name__ == "__main__":
    unittest.main()
