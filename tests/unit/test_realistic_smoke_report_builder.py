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
_format_opinion_line = _generate_realistic_smoke._format_opinion_line
_validate_comparisons_consistency = _generate_realistic_smoke._validate_comparisons_consistency
build_comparisons_report = _generate_realistic_smoke.build_comparisons_report
classify_humanity_delta = _generate_realistic_smoke.classify_humanity_delta


def _scenario(name: str, delta: float) -> dict:
    return {
        "scenario": name,
        "comparison": {"humanity_delta": delta},
        "pre_rebalance": {"metrics": {"mono_day_ratio": 1.0}},
        "post_rebalance": {"metrics": {"mono_day_ratio": 0.5}},
    }


@pytest.mark.parametrize(
    ("delta", "expected_label"),
    [
        (0.0, "marginale"),
        (0.0999, "marginale"),
        (0.1, "marginale"),
        (0.1001, "moderato"),
        (0.2999, "moderato"),
        (0.3, "moderato"),
        (0.3001, "forte"),
        (0.75, "forte"),
        (-0.75, "forte"),
    ],
)
def test_classify_humanity_delta_threshold_edges(delta: float, expected_label: str) -> None:
    assert classify_humanity_delta(delta) == expected_label


def test_build_comparisons_assigns_labels_from_thresholds() -> None:
    comparisons = build_comparisons_report(
        [_scenario("delta_zero", 0.0), _scenario("delta_mid", 0.2), _scenario("delta_high", 0.45)],
        _build_opinion_thresholds(),
    )

    labels = [item["opinion"]["label"] for item in comparisons["comparisons"]]
    assert labels == ["marginale", "moderato", "forte"]
    _validate_comparisons_consistency(comparisons)


def test_format_opinion_line_keeps_delta_and_direction_coherent() -> None:
    item = {
        "scenario": "scenario_coerente",
        "humanity_delta": -0.3123,
        "opinion": {"label": "forte", "text": "unused"},
        "mono_day_ratio": {"pre": 1.0, "post": 0.7},
    }

    line = _format_opinion_line(item)

    assert "**scenario_coerente**" in line
    assert "impatto **forte**" in line
    assert "(calo)" in line
    assert "Δ=-0.3123" in line


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
