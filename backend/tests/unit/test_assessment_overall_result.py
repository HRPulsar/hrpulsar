"""HRP-63: overall result on the assessment detail page.

The calculation is a plain mean of per-competence percents with half-up
rounding to int. Edge cases that matter in production:

- Some competences may still have ``percent is None`` (no rating scale yet,
  or empty answers). Those are skipped.
- All competences ``None`` → ``overall_percent`` is None (the UI hides the
  badge).
- Half-up rounding (e.g. 84.5 → 85) is what the spec calls out as
  standard half-up rounding, distinct from Python's banker's ``round``.
"""

from __future__ import annotations

from app.modules.assessment.service import compute_overall_percent


class TestComputeOverallPercent:
    def test_returns_mean_for_full_results(self) -> None:
        # spec example: 90, 81, 80 → 83.66… → 84
        assert compute_overall_percent([90, 81, 80]) == 84

    def test_skips_none_values(self) -> None:
        # one competence without a scale yet — averaged over the rest
        assert compute_overall_percent([100, None, 50]) == 75

    def test_none_when_all_missing(self) -> None:
        assert compute_overall_percent([None, None]) is None
        assert compute_overall_percent([]) is None

    def test_half_up_not_bankers(self) -> None:
        # round() in Python returns 84 for 84.5 (banker's rounding to even),
        # the spec requires 85. compute_overall_percent must agree with QA.
        assert compute_overall_percent([85, 84]) == 85  # mean 84.5 → 85
        assert compute_overall_percent([83, 84]) == 84  # mean 83.5 → 84
        assert compute_overall_percent([82, 83]) == 83  # mean 82.5 → 83

    def test_single_value(self) -> None:
        assert compute_overall_percent([77]) == 77

    def test_all_zero(self) -> None:
        assert compute_overall_percent([0, 0, 0]) == 0
