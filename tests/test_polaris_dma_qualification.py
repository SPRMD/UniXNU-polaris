"""Run the UFS DMA qualification cases under the default test discovery.

The evaluator, its evidence template and its cases live under research/ because
they are decision aids for hardware qualification, not runtime code. Hosted CI
runs 'python -m unittest discover -s tests', so re-export those cases here
instead of duplicating them; a divergence would otherwise go unnoticed.

The evaluator only reads recorded evidence. It never opens the phone, maps MMIO,
touches UFS or the apps-SMMU, and it does not weaken
drivers/ShengUfs/PolarisDmaHandoff.h.
"""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "research_dma_qualification_cases", ROOT / "research" / "test_polaris_dma_qualification.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

# Re-exported classes are collected by unittest's default loader.
globals().update({
    name: value for name, value in vars(MODULE).items()
    if isinstance(value, type) and issubclass(value, unittest.TestCase)
})
