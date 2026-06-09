"""Tests for ReconTracker — scout and disinform state management."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from histrategy_engine.ai.recon import ReconTracker


class TestReconTracker:
    """Tests for reconnaissance tracker."""

    def setup_method(self):
        self.tracker = ReconTracker()

    def test_scout_costs(self):
        assert ReconTracker.SCOUT_COST == 200
        assert ReconTracker.DISINFORM_COST == 300

    def test_scout_marks_territory(self):
        msg = self.tracker.scout("shu", "wancheng")
        assert "侦察成功" in msg
        assert self.tracker.is_scouted("shu", "wancheng")

    def test_scout_not_visible_to_other_faction(self):
        self.tracker.scout("shu", "wancheng")
        assert not self.tracker.is_scouted("cao", "wancheng")

    def test_scout_expires(self):
        self.tracker.scout("shu", "xinye")
        # Tick 3 times → should expire
        for _ in range(3):
            self.tracker.tick_turn()
        # After 3 turns it should be gone
        assert not self.tracker.is_scouted("shu", "xinye")

    def test_disinformation(self):
        self.tracker.disinform("shu", "wancheng", 50000)
        fake = self.tracker.get_disinformation("shu", "wancheng")
        assert fake == 50000

        # Other faction not affected
        assert self.tracker.get_disinformation("cao", "wancheng") is None

    def test_serialization(self):
        self.tracker.scout("shu", "wancheng")
        self.tracker.disinform("cao", "xinye", 99999)

        data = self.tracker.to_dict()
        restored = ReconTracker.from_dict(data)

        assert restored.is_scouted("shu", "wancheng")
        assert restored.get_disinformation("cao", "xinye") == 99999
