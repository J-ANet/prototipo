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
_opinion_payload = _generate_realistic_smoke._opinion_payload
_validate_comparisons_consistency = _generate_realistic_smoke._validate_comparisons_consistency
build_comparisons_report = _generate_realistic_smoke.build_comparisons_report
classify_humanity_delta = _generate_realistic_smoke.classify_humanity_delta
_evaluate_metrics = _generate_realistic_smoke._evaluate_metrics


def _scenario(
    name: str,
    delta: float,
    *,
    role: str,
    post_humanity: float,
    post_mono: float,
    post_streak: float,
    post_switch: float,
) -> dict:
    return {
        "scenario": name,
        "cross_scenario_role": role,
        "comparison": {"humanity_delta": delta},
        "pre_rebalance": {"metrics": {"mono_day_ratio": 1.0}},
        "post_rebalance": {
            "metrics": {
                "humanity_score": post_humanity,
                "mono_day_ratio": post_mono,
                "max_same_subject_streak_days": post_streak,
                "switch_rate": post_switch,
            }
        },
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
        [
            _scenario(
                "delta_zero",
                0.0,
                role="forward",
                post_humanity=0.5,
                post_mono=0.8,
                post_streak=3,
                post_switch=0.2,
            ),
            _scenario(
                "delta_mid",
                0.2,
                role="backward",
                post_humanity=0.6,
                post_mono=0.7,
                post_streak=2,
                post_switch=0.25,
            ),
            _scenario(
                "delta_high",
                0.45,
                role="neutral",
                post_humanity=0.55,
                post_mono=0.75,
                post_streak=2,
                post_switch=0.23,
            ),
        ],
        _build_opinion_thresholds(),
    )

    labels = [item["opinion"]["label"] for item in comparisons["comparisons"]]
    assert labels == ["marginale", "moderato", "forte"]
    assert comparisons["cross_scenario"]["backward_minus_forward_humanity_score"] == 0.1
    _validate_comparisons_consistency(comparisons)


def test_build_comparisons_report_adds_coherent_cross_scenario_block() -> None:
    comparisons = build_comparisons_report(
        [
            _scenario(
                "forward_case",
                0.0,
                role="forward",
                post_humanity=0.51,
                post_mono=0.82,
                post_streak=3,
                post_switch=0.11,
            ),
            _scenario(
                "backward_case",
                0.0,
                role="backward",
                post_humanity=0.63,
                post_mono=0.76,
                post_streak=2,
                post_switch=0.17,
            ),
        ],
        _build_opinion_thresholds(),
    )

    cross = comparisons["cross_scenario"]
    assert cross["forward_scenario"] == "forward_case"
    assert cross["backward_scenario"] == "backward_case"
    assert cross["backward_minus_forward_humanity_score"] == 0.12
    assert cross["backward_minus_forward_mono_day_ratio"] == -0.06
    assert cross["backward_minus_forward_max_streak_days"] == -1.0
    assert cross["backward_minus_forward_switch_rate"] == 0.06


def test_format_opinion_line_keeps_delta_and_direction_coherent() -> None:
    item = {
        "scenario": "scenario_coerente",
        "humanity_delta": -0.3123,
        "opinion": {"label": "forte", "direction": "negative", "trend": "peggioramento", "text": "unused"},
        "mono_day_ratio": {"pre": 1.0, "post": 0.7},
    }

    line = _format_opinion_line(item)

    assert "**scenario_coerente**" in line
    assert "impatto **forte**" in line
    assert "peggioramento" in line
    assert "Δ=-0.3123" in line


@pytest.mark.parametrize(
    ("delta", "expected_direction", "expected_trend", "expected_label"),
    [
        (0.0, "neutral", "stabile", "marginale"),
        (0.2, "positive", "miglioramento", "moderato"),
        (-0.45, "negative", "peggioramento", "forte"),
    ],
)
def test_opinion_payload_keeps_text_label_and_delta_sign_coherent(
    delta: float,
    expected_direction: str,
    expected_trend: str,
    expected_label: str,
) -> None:
    payload = _opinion_payload(delta, _build_opinion_thresholds())

    assert payload["label"] == expected_label
    assert payload["direction"] == expected_direction
    assert payload["trend"] == expected_trend
    assert expected_trend in payload["text"]
    assert f"Δ={delta:+.4f}" in payload["text"]


def test_validate_comparisons_fails_on_incoherent_label_delta() -> None:
    comparisons = {
        "opinion_thresholds": _build_opinion_thresholds(),
        "comparisons": [
            {
                "scenario": "bad_case",
                "humanity_delta": 0.35,
                "opinion": {
                    "label": "marginale",
                    "direction": "positive",
                    "trend": "miglioramento",
                    "text": "Impatto marginale",
                },
                "mono_day_ratio": {"pre": 1.0, "post": 0.8},
            }
        ],
        "cross_scenario": {
            "forward_scenario": "forward_case",
            "backward_scenario": "backward_case",
            "backward_minus_forward_humanity_score": 0.35,
            "backward_minus_forward_mono_day_ratio": -0.2,
            "backward_minus_forward_max_streak_days": 0.0,
            "backward_minus_forward_switch_rate": 0.0,
        },
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
        "scenarios": [
            {"post_rebalance": {"accepted_swaps": 1}},
            {"post_rebalance": {"accepted_swaps": 0}},
        ],
        "summary": {
            "status": "pass",
            "quality_status": "fail",
            "humanity_delta": 0.1234,
        },
    }
    comparisons = {
        "opinion_thresholds": _build_opinion_thresholds(),
        "cross_scenario": {
            "forward_scenario": "off_monotone",
            "backward_scenario": "balanced_diffuse",
            "backward_minus_forward_humanity_score": 0.16,
            "backward_minus_forward_mono_day_ratio": -0.1,
            "backward_minus_forward_max_streak_days": -1.0,
            "backward_minus_forward_switch_rate": 0.03,
        },
        "comparisons": [
            {
                "scenario": "balanced_diffuse",
                "humanity_delta": 0.12,
                "opinion": {
                    "label": "moderato",
                    "direction": "positive",
                    "trend": "miglioramento",
                    "text": "unused",
                },
                "mono_day_ratio": {"pre": 0.9, "post": 0.7},
            }
        ],
    }

    readme = _generate_realistic_smoke.build_results_readme(report, comparisons)

    assert "Acceptance status (`summary.status`): **pass**" in readme
    assert "Quality status (`summary.quality_status`): **fail**" in readme
    assert "pass ma da migliorare" in readme


def test_build_results_readme_adds_limitations_when_no_swaps_are_accepted() -> None:
    report = {
        "scenarios": [
            {"post_rebalance": {"accepted_swaps": 0}},
            {"post_rebalance": {"accepted_swaps": 0}},
        ],
        "summary": {
            "status": "pass",
            "quality_status": "pass",
            "humanity_delta": 0.0,
        },
    }
    comparisons = {
        "opinion_thresholds": _build_opinion_thresholds(),
        "cross_scenario": {
            "forward_scenario": "off_monotone",
            "backward_scenario": "balanced_diffuse",
            "backward_minus_forward_humanity_score": 0.0,
            "backward_minus_forward_mono_day_ratio": 0.0,
            "backward_minus_forward_max_streak_days": 0.0,
            "backward_minus_forward_switch_rate": 0.0,
        },
        "comparisons": [
            {
                "scenario": "balanced_diffuse",
                "humanity_delta": 0.0,
                "opinion": {
                    "label": "marginale",
                    "direction": "neutral",
                    "trend": "stabile",
                    "text": "unused",
                },
                "mono_day_ratio": {"pre": 0.9, "post": 0.9},
            }
        ],
    }

    readme = _generate_realistic_smoke.build_results_readme(report, comparisons)

    assert "## Limitazioni del run" in readme
    assert "accepted_swaps == 0" in readme
