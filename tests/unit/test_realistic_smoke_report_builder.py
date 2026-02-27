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
_evaluate_metrics = _generate_realistic_smoke._evaluate_metrics


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


def test_evaluate_metrics_exposes_acceptance_and_quality_statuses() -> None:
    case = {
        "acceptance_min_humanity_score": 0.5,
        "acceptance_max_mono_day_ratio": 0.9,
        "acceptance_min_switch_rate": 0.1,
        "acceptance_max_same_subject_streak_days_target": 3,
        "acceptance_min_subject_variety_index": 0.5,
        "quality_min_humanity_score": 0.65,
        "quality_max_mono_day_ratio": 0.7,
        "quality_min_switch_rate": 0.2,
        "quality_max_same_subject_streak_days_target": 2,
        "quality_min_subject_variety_index": 0.65,
    }
    metrics = {
        "confidence_score": 0.9,
        "humanity_score": 0.58,
        "mono_day_ratio": 0.75,
        "switch_rate": 0.15,
        "max_same_subject_streak_days": 2,
        "subject_variety_index": 0.55,
    }

    compact, checks = _evaluate_metrics(case, metrics)

    assert compact["confidence_score"] == 0.9
    assert checks["acceptance_checks"]["humanity_score"]["status"] == "pass"
    assert checks["acceptance_checks"]["switch_rate"]["status"] == "pass"
    assert checks["quality_checks"]["humanity_score"]["status"] == "fail"
    assert checks["quality_checks"]["switch_rate"]["status"] == "fail"


def test_build_results_readme_mentions_double_gate_status() -> None:
    report = {
        "summary": {
            "status": "pass",
            "quality_status": "fail",
            "humanity_delta": 0.1234,
        }
    }
    comparisons = {
        "opinion_thresholds": _build_opinion_thresholds(),
        "comparisons": [
            {
                "scenario": "balanced_diffuse",
                "humanity_delta": 0.12,
                "opinion": {"label": "moderato", "text": "unused"},
                "mono_day_ratio": {"pre": 0.9, "post": 0.7},
            }
        ],
    }

    readme = _generate_realistic_smoke.build_results_readme(report, comparisons)

    assert "Acceptance status (`summary.status`): **pass**" in readme
    assert "Quality status (`summary.quality_status`): **fail**" in readme
    assert "pass ma da migliorare" in readme
