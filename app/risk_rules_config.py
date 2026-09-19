"""Configurable thresholds for deterministic execution risk rules."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskThresholds:
    coverage_days_critical: float = 1.0
    coverage_days_high: float = 3.0
    shortfall_units_high: int = 5
    facing_below_min_high: bool = True
    count_mismatch_critical: bool = True
    not_found_row_high: int = 3


DEFAULT_RISK_THRESHOLDS = RiskThresholds()
