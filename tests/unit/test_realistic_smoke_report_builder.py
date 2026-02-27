from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "generate_realistic_smoke.py"
_SPEC = importlib.util.spec_from_file_location("generate_realistic_smoke", MODULE_PATH)
assert _SPEC and _SPEC.loader
_generate_realistic_smoke = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_generate_realistic_smoke)

_build_opinion_thresholds = _generate_realistic_smoke._build_opinion_thresholds
_validate_comparisons_consistency = _generate_realistic_smoke._validate_comparisons_consistency
build_comparisons_report = _generate_realistic_smoke.build_comparisons_report


def _scenario(name: str, delta: float) -> dict:
    return {
        "scenario": name,
        "comparison": {"humanity_delta": delta},
        "pre_rebalance": {"metrics": {"mono_day_ratio": 1.0}},
        "post_rebalance": {"metrics": {"mono_day_ratio": 0.5}},
    }


def test_build_comparisons_assigns_marginale_for_zero_delta() -> None:
    comparisons = build_comparisons_report([_scenario("delta_zero", 0.0)], _build_opinion_thresholds())

    assert comparisons["comparisons"][0]["opinion"]["label"] == "marginale"
    _validate_comparisons_consistency(comparisons)


def test_build_comparisons_assigns_moderato_for_mid_delta() -> None:
    comparisons = build_comparisons_report([_scenario("delta_mid", 0.2)], _build_opinion_thresholds())

    assert comparisons["comparisons"][0]["opinion"]["label"] == "moderato"
    _validate_comparisons_consistency(comparisons)


def test_build_comparisons_assigns_forte_for_high_delta() -> None:
    comparisons = build_comparisons_report([_scenario("delta_high", 0.45)], _build_opinion_thresholds())

    assert comparisons["comparisons"][0]["opinion"]["label"] == "forte"
    _validate_comparisons_consistency(comparisons)


def test_validate_comparisons_fails_on_incoherent_label_delta() -> None:
    comparisons = {
        "opinion_thresholds": _build_opinion_thresholds(),
        "comparisons": [
            {
                "scenario": "bad_case",
                "humanity_delta": 0.35,
                "opinion": {"label": "marginale", "text": "Impatto marginale"},
                "mono_day_ratio": {"pre": 1.0, "post": 0.8},
            }
        ],
    }

    with pytest.raises(ValueError, match="Incoerenza opinione/delta"):
        _validate_comparisons_consistency(comparisons)
