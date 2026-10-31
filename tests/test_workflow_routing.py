from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-workflow-routing.py"
SPEC = importlib.util.spec_from_file_location("workflow_routing", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class WorkflowRoutingTests(unittest.TestCase):
    def test_build_is_main_push_and_manual_only(self) -> None:
        report = MODULE.validate(
            build_workflow=ROOT / ".github" / "workflows" / "polaris-build.yml",
            legacy_workflow=ROOT / ".github" / "workflows" / "checks.yml",
        )
        self.assertTrue(report["build_has_main_push"])
        self.assertTrue(report["build_has_manual_dispatch"])
        self.assertFalse(report["legacy_has_push"])


if __name__ == "__main__":
    unittest.main()
