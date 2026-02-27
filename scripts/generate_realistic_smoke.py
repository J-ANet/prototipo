from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from planner.engine import run_planner
from planner.metrics import collect_metrics
from planner.normalization import resolve_effective_config
from planner.validation import ValidationReport

OUT = ROOT / "results" / "realistic_smoke" / "realism_checks.json"
COMPARISONS_OUT = ROOT / "results" / "realistic_smoke" / "comparisons.json"
README_OUT = ROOT / "results" / "realistic_smoke" / "README.md"


def _build_opinion_thresholds() -> list[dict]:
    return [
        {"label": "marginale", "max_abs_delta": 0.1},
        {"label": "moderato", "max_abs_delta": 0.3},
        {"label": "forte", "max_abs_delta": 1.0},
    ]


def _build_delta_language_rules() -> dict[str, str]:
    return {
        "positive": "miglioramento",
        "negative": "peggioramento",
        "neutral": "stabile",
    }


def _opinion_label_for_delta(delta: float, thresholds: list[dict]) -> str:
    abs_delta = abs(delta)
    for band in thresholds:
        if abs_delta <= float(band["max_abs_delta"]):
            return str(band["label"])
    return str(thresholds[-1]["label"])


def classify_humanity_delta(delta: float) -> str:
    return _opinion_label_for_delta(delta, _build_opinion_thresholds())


def _delta_direction(delta: float) -> str:
    if delta > 0:
        return "positive"
    if delta < 0:
        return "negative"
    return "neutral"


def _opinion_text(delta: float, label: str) -> str:
    direction = _delta_direction(delta)
    trend = _build_delta_language_rules()[direction]
    return f"Impatto {label}: {trend} su humanity_score (Δ={delta:+.4f})."


def _opinion_payload(delta: float, thresholds: list[dict]) -> dict[str, str]:
    label = _opinion_label_for_delta(delta, thresholds)
    direction = _delta_direction(delta)
    return {
        "label": label,
        "direction": direction,
        "trend": _build_delta_language_rules()[direction],
        "text": _opinion_text(delta, label),
    }


def _format_opinion_line(item: dict) -> str:
    delta = float(item["humanity_delta"])
    opinion = item["opinion"]
    label = str(opinion["label"])
    trend = str(opinion["trend"])
    return f"- **{item['scenario']}**: impatto **{label}**, {trend} su humanity_score, con Δ={delta:+.4f}."


def _format_threshold_lines(thresholds: list[dict]) -> list[str]:
    lines: list[str] = []
    lower = 0.0
    for idx, band in enumerate(sorted(thresholds, key=lambda item: float(item["max_abs_delta"]))):
        label = str(band["label"])
        upper = float(band["max_abs_delta"])
        if idx == 0:
            lines.append(f"- `{label}`: `abs(delta) < {upper:.4f}`")
        elif idx == len(thresholds) - 1:
            lines.append(f"- `{label}`: `abs(delta) >= {lower:.4f}`")
        else:
            lines.append(f"- `{label}`: `{lower:.4f} <= abs(delta) < {upper:.4f}`")
        lower = upper
    return lines


def build_comparisons_report(scenarios: list[dict], thresholds: list[dict]) -> dict:
    comparison_items = []
    for scenario in scenarios:
        delta = float(scenario["comparison"]["humanity_delta"])
        opinion = _opinion_payload(delta, thresholds)
        comparison_items.append(
            {
                "scenario": scenario["scenario"],
                "humanity_delta": round(delta, 4),
                "opinion": opinion,
                "mono_day_ratio": {
                    "pre": float(scenario["pre_rebalance"]["metrics"]["mono_day_ratio"]),
                    "post": float(scenario["post_rebalance"]["metrics"]["mono_day_ratio"]),
                },
            }
        )
    role_to_scenario = {
        str(scenario.get("cross_scenario_role", "")): scenario
        for scenario in scenarios
        if scenario.get("cross_scenario_role") in {"forward", "backward"}
    }
    if "forward" not in role_to_scenario or "backward" not in role_to_scenario:
        raise ValueError("Serve almeno una coppia forward/backward per calcolare le metriche cross_scenario")

    forward_metrics = role_to_scenario["forward"]["post_rebalance"]["metrics"]
    backward_metrics = role_to_scenario["backward"]["post_rebalance"]["metrics"]
    cross_scenario = {
        "forward_scenario": role_to_scenario["forward"]["scenario"],
        "backward_scenario": role_to_scenario["backward"]["scenario"],
        "backward_minus_forward_humanity_score": round(
            float(backward_metrics["humanity_score"]) - float(forward_metrics["humanity_score"]),
            4,
        ),
        "backward_minus_forward_mono_day_ratio": round(
            float(backward_metrics["mono_day_ratio"]) - float(forward_metrics["mono_day_ratio"]),
            4,
        ),
        "backward_minus_forward_max_streak_days": round(
            float(backward_metrics["max_same_subject_streak_days"]) - float(forward_metrics["max_same_subject_streak_days"]),
            4,
        ),
        "backward_minus_forward_switch_rate": round(
            float(backward_metrics["switch_rate"]) - float(forward_metrics["switch_rate"]),
            4,
        ),
    }
    return {"opinion_thresholds": thresholds, "comparisons": comparison_items, "cross_scenario": cross_scenario}


def _validate_comparisons_consistency(comparisons: dict) -> None:
    thresholds = comparisons["opinion_thresholds"]
    sorted_thresholds = sorted(thresholds, key=lambda item: float(item["max_abs_delta"]))
    bounds: dict[str, tuple[float, float]] = {}
    lower = 0.0
    for band in sorted_thresholds:
        label = str(band["label"])
        upper = float(band["max_abs_delta"])
        bounds[label] = (lower, upper)
        lower = upper

    for item in comparisons["comparisons"]:
        raw_delta = float(item["humanity_delta"])
        delta = abs(raw_delta)
        opinion = item["opinion"]
        label = str(opinion["label"])
        if label not in bounds:
            raise ValueError(f"Opinion label non riconosciuta: {label}")
        lower_bound, upper_bound = bounds[label]
        if not (lower_bound <= delta <= upper_bound):
            raise ValueError(
                "Incoerenza opinione/delta per "
                f"{item['scenario']}: label={label}, delta={delta:.4f}, "
                f"atteso in [{lower_bound:.4f}, {upper_bound:.4f}]"
            )

        expected_direction = _delta_direction(raw_delta)
        expected_trend = _build_delta_language_rules()[expected_direction]
        if str(opinion.get("direction", "")) != expected_direction:
            raise ValueError(
                f"Incoerenza direction/delta per {item['scenario']}: "
                f"direction={opinion.get('direction')}, atteso={expected_direction}"
            )
        if str(opinion.get("trend", "")) != expected_trend:
            raise ValueError(
                f"Incoerenza trend/delta per {item['scenario']}: "
                f"trend={opinion.get('trend')}, atteso={expected_trend}"
            )
        expected_text = _opinion_text(raw_delta, label)
        if str(opinion.get("text", "")) != expected_text:
            raise ValueError(
                f"Incoerenza testo/delta per {item['scenario']}: "
                f"text={opinion.get('text')!r}, atteso={expected_text!r}"
            )


def _quality_failure_suggestion(metric_name: str, check: dict) -> str:
    if metric_name == "max_same_subject_streak_days":
        return "Riduci la concentrazione per materia e forza più alternanza giornaliera."
    if metric_name == "mono_day_ratio":
        return "Distribuisci almeno una seconda materia nei giorni mono-materia."
    if metric_name == "switch_rate":
        return "Aumenta i cambi materia tra blocchi consecutivi riducendo blocchi troppo lunghi."
    if metric_name == "humanity_score":
        return "Bilancia varietà/switch/streak per aumentare la qualità percepita del piano."
    if metric_name == "subject_variety_index":
        return "Aumenta il numero di materie attive sul periodo con una distribuzione più diffusa."
    return "Ricalibra i vincoli di distribuzione per rispettare il quality gate."


def _collect_quality_fail_reasons(scenarios: list[dict]) -> list[dict]:
    fail_reasons: list[dict] = []
    for scenario in scenarios:
        scenario_name = str(scenario["scenario"])
        for phase_name in ("pre_rebalance", "post_rebalance"):
            phase = scenario.get(phase_name, {})
            quality_checks = phase.get("quality_checks", {})
            for metric_name, check in quality_checks.items():
                if check.get("status") != "fail":
                    continue
                threshold_key = "threshold_min" if "threshold_min" in check else "threshold_max"
                fail_reasons.append(
                    {
                        "scenario": scenario_name,
                        "phase": phase_name,
                        "metric": metric_name,
                        "value": float(check["value"]),
                        "threshold_key": threshold_key,
                        "threshold": float(check[threshold_key]),
                        "suggestion": _quality_failure_suggestion(metric_name, check),
                    }
                )

    return fail_reasons


def build_results_readme(report: dict, comparisons: dict) -> str:
    threshold_rows = _format_threshold_lines(comparisons["opinion_thresholds"])
    opinion_lines = []
    mono_rows = []
    for item in comparisons["comparisons"]:
        opinion_lines.append(_format_opinion_line(item))
        mono_rows.append(
            f"| `{item['scenario']}` | {item['mono_day_ratio']['pre']:.4f} | {item['mono_day_ratio']['post']:.4f} |"
        )
    cross = comparisons["cross_scenario"]

    def _delta_interpretation(delta: float, higher_is_better: bool) -> str:
        if delta == 0:
            return "parità"
        better_for = "backward" if (delta > 0) == higher_is_better else "forward"
        return f"vantaggio {better_for}"

    cross_rows = [
        (
            "humanity_score",
            float(cross["backward_minus_forward_humanity_score"]),
            _delta_interpretation(float(cross["backward_minus_forward_humanity_score"]), higher_is_better=True),
        ),
        (
            "mono_day_ratio",
            float(cross["backward_minus_forward_mono_day_ratio"]),
            _delta_interpretation(float(cross["backward_minus_forward_mono_day_ratio"]), higher_is_better=False),
        ),
        (
            "max_streak_days",
            float(cross["backward_minus_forward_max_streak_days"]),
            _delta_interpretation(float(cross["backward_minus_forward_max_streak_days"]), higher_is_better=False),
        ),
        (
            "switch_rate",
            float(cross["backward_minus_forward_switch_rate"]),
            _delta_interpretation(float(cross["backward_minus_forward_switch_rate"]), higher_is_better=True),
        ),
    ]

    quality_fail_reasons = report.get("summary", {}).get("quality_fail_reasons", [])
    quality_failure_rows = [
        (
            item["scenario"],
            item["phase"],
            item["metric"],
            item["threshold_key"],
            float(item["threshold"]),
            float(item["value"]),
            item["suggestion"],
        )
        for item in quality_fail_reasons
    ]
    quality_fail_section = (
        [
            "",
            "## Metriche quality fallite",
            "",
            "| Scenario | Fase | Metrica | Threshold | Valore | Suggerimento |",
            "| --- | --- | --- | ---: | ---: | --- |",
            *[
                f"| `{scenario}` | `{phase}` | `{metric}` | `{threshold_key}={threshold:.4f}` | {value:.4f} | {suggestion} |"
                for scenario, phase, metric, threshold_key, threshold, value, suggestion in quality_failure_rows
            ],
        ]
        if quality_failure_rows
        else ["", "## Metriche quality fallite", "", "Nessuna metrica quality fallita."]
    )

    scenario_rows = report.get("scenarios", [])
    no_accepted_swaps = bool(scenario_rows) and all(
        int(item["post_rebalance"].get("accepted_swaps", 0)) == 0 for item in scenario_rows
    )
    limitations_section = (
        [
            "",
            "## Limitazioni del run",
            "- `accepted_swaps == 0` in tutti gli scenari: il rebalance non ha applicato swap accettati.",
            "- Le variazioni osservate riflettono solo il piano iniziale e i vincoli correnti, senza correzioni da swap.",
        ]
        if no_accepted_swaps
        else []
    )

    interpretation_line = (
        "- Interpretazione: se acceptance è `pass` ma quality è `fail`, il piano è **pass ma da migliorare**."
        if report["summary"]["status"] == "pass" and report["summary"]["quality_status"] == "fail"
        else "- Interpretazione: acceptance e quality sono coerenti, senza warning aggiuntivi."
    )

    return "\n".join(
        [
            "# Realistic smoke results",
            "",
            "Questo report espone **confidence** e **qualità umana** del piano.",
            "",
            "## Metriche chiave",
            "- `confidence_score`: fattibilità complessiva del piano.",
            "- `humanity_score` (0-1): qualità percepita della distribuzione, aggregata da varietà/switch/streak.",
            "- `mono_day_ratio` (0-1): quota di giorni con una sola materia.",
            "- `max_same_subject_streak_days`: massima striscia consecutiva di giorni dominati dalla stessa materia.",
            "- `switch_rate` (0-1): frequenza cambi materia tra blocchi consecutivi.",
            "",
            "## Opinione (data-driven da `comparisons.json`)",
            "",
            "Soglie `abs(humanity_delta)` usate nell'audit smoke:",
            *threshold_rows,
            "",
            *opinion_lines,
            "",
            "## Mini-tabella verificabilità (mono_day_ratio)",
            "",
            "| Scenario | Mono ratio pre | Mono ratio post |",
            "| --- | ---: | ---: |",
            *mono_rows,
            "",
            "## Forward vs Backward",
            "",
            f"Confronto `backward - forward` tra **{cross['backward_scenario']}** e **{cross['forward_scenario']}**.",
            "",
            "| Metrica | Delta (backward-forward) | Interpretazione |",
            "| --- | ---: | --- |",
            *[f"| `{name}` | {delta:+.4f} | {interp} |" for name, delta, interp in cross_rows],
            *quality_fail_section,
            *limitations_section,
            "",
            "## Stato finale",
            f"- Acceptance status (`summary.status`): **{report['summary']['status']}**",
            f"- Quality status (`summary.quality_status`): **{report['summary']['quality_status']}**",
            f"- Humanity delta aggregato: `{report['summary']['humanity_delta']:+.4f}`",
            interpretation_line,
            "",
            "## Gate di valutazione",
            "- `acceptance_checks`: requisito minimo di fattibilità (usato per lo stato ufficiale).",
            "- `quality_checks`: target qualitativo più severo, utile per evidenziare margini di miglioramento.",
            "- Il report globale resta basato su acceptance (`summary.status`) e aggiunge `summary.quality_status`.",
            "",
            "## Come rigenerare",
            "```bash",
            "python scripts/generate_realistic_smoke.py",
            "```",
            "",
            "Output prodotti:",
            "- `results/realistic_smoke/realism_checks.json`",
            "- `results/realistic_smoke/comparisons.json`",
        ]
    )


def _evaluate_metrics(case: dict, metrics: dict) -> tuple[dict, dict]:
    humanity_score = float(metrics.get("humanity_score", 0.0) or 0.0)
    mono_day_ratio = float(metrics.get("mono_day_ratio", 1.0) or 1.0)
    switch_rate = float(metrics.get("switch_rate", 0.0) or 0.0)
    max_streak_days = float(metrics.get("max_same_subject_streak_days", 0.0) or 0.0)
    subject_variety_index = float(metrics.get("subject_variety_index", 0.0) or 0.0)

    acceptance_checks = {
        "humanity_score": {
            "value": round(humanity_score, 4),
            "threshold_min": case["acceptance_min_humanity_score"],
            "status": "pass" if humanity_score >= case["acceptance_min_humanity_score"] else "fail",
        },
        "mono_day_ratio": {
            "value": round(mono_day_ratio, 4),
            "threshold_max": case["acceptance_max_mono_day_ratio"],
            "status": "pass" if mono_day_ratio <= case["acceptance_max_mono_day_ratio"] else "fail",
        },
        "switch_rate": {
            "value": round(switch_rate, 4),
            "threshold_min": case["acceptance_min_switch_rate"],
            "status": "pass" if switch_rate >= case["acceptance_min_switch_rate"] else "fail",
        },
        "max_same_subject_streak_days": {
            "value": round(max_streak_days, 4),
            "threshold_max": case.get("acceptance_max_same_subject_streak_days_target", 99),
            "status": "pass"
            if max_streak_days <= case.get("acceptance_max_same_subject_streak_days_target", 99)
            else "fail",
        },
        "subject_variety_index": {
            "value": round(subject_variety_index, 4),
            "threshold_min": case.get("acceptance_min_subject_variety_index", 0.0),
            "status": "pass"
            if subject_variety_index >= case.get("acceptance_min_subject_variety_index", 0.0)
            else "fail",
        },
    }

    quality_checks = {
        "humanity_score": {
            "value": round(humanity_score, 4),
            "threshold_min": case["quality_min_humanity_score"],
            "status": "pass" if humanity_score >= case["quality_min_humanity_score"] else "fail",
        },
        "mono_day_ratio": {
            "value": round(mono_day_ratio, 4),
            "threshold_max": case["quality_max_mono_day_ratio"],
            "status": "pass" if mono_day_ratio <= case["quality_max_mono_day_ratio"] else "fail",
        },
        "switch_rate": {
            "value": round(switch_rate, 4),
            "threshold_min": case["quality_min_switch_rate"],
            "status": "pass" if switch_rate >= case["quality_min_switch_rate"] else "fail",
        },
        "max_same_subject_streak_days": {
            "value": round(max_streak_days, 4),
            "threshold_max": case.get("quality_max_same_subject_streak_days_target", 99),
            "status": "pass"
            if max_streak_days <= case.get("quality_max_same_subject_streak_days_target", 99)
            else "fail",
        },
        "subject_variety_index": {
            "value": round(subject_variety_index, 4),
            "threshold_min": case.get("quality_min_subject_variety_index", 0.0),
            "status": "pass" if subject_variety_index >= case.get("quality_min_subject_variety_index", 0.0) else "fail",
        },
    }

    compact = {
        "confidence_score": round(float(metrics.get("confidence_score", 0.0) or 0.0), 4),
        "humanity_score": round(humanity_score, 4),
        "mono_day_ratio": round(mono_day_ratio, 4),
        "max_same_subject_streak_days": round(max_streak_days, 4),
        "switch_rate": round(switch_rate, 4),
        "subject_variety_index": round(subject_variety_index, 4),
    }
    return compact, {"acceptance_checks": acceptance_checks, "quality_checks": quality_checks}


def _subject_indicators(result: dict) -> dict[str, dict[str, float | str]]:
    per_subject_minutes_by_day: dict[str, dict[str, int]] = {}
    for slot in result.get("plan", []):
        sid = str(slot.get("subject_id", ""))
        if not sid or sid == "__slack__" or slot.get("bucket") != "base":
            continue
        day = str(slot.get("date", ""))
        per_subject_minutes_by_day.setdefault(sid, {})
        per_subject_minutes_by_day[sid][day] = per_subject_minutes_by_day[sid].get(day, 0) + int(slot.get("minutes", 0) or 0)

    concentration_by_subject: dict[str, str] = {}
    concentration_origin_by_subject: dict[str, str] = {}
    for item in result.get("decision_trace", []):
        sid = str(item.get("selected_subject_id", ""))
        metadata = item.get("allocation_metadata", {})
        if sid in {"", "__slack__"} or metadata.get("phase") != "base":
            continue
        concentration_by_subject.setdefault(sid, str(metadata.get("concentration_mode", "")))
        concentration_origin_by_subject.setdefault(sid, str(metadata.get("concentration_origin", "")))

    indicators: dict[str, dict[str, float | str]] = {}
    for sid, daily in per_subject_minutes_by_day.items():
        sorted_days = sorted(daily)
        total_minutes = sum(daily.values())
        longest_streak = 0
        current_streak = 0
        previous_day = None
        for day in sorted_days:
            day_number = int(day.split("-")[-1])
            if previous_day is not None and day_number == previous_day + 1:
                current_streak += 1
            else:
                current_streak = 1
            longest_streak = max(longest_streak, current_streak)
            previous_day = day_number

        indicators[sid] = {
            "concentration_mode": concentration_by_subject.get(sid, "unknown"),
            "concentration_origin": concentration_origin_by_subject.get(sid, "unknown"),
            "active_days": float(len(daily)),
            "longest_streak_days": float(longest_streak),
            "max_day_minutes": float(max(daily.values()) if daily else 0),
            "clustering_ratio": round((max(daily.values()) / total_minutes) if total_minutes > 0 else 0.0, 4),
        }

    return indicators


def _run_single(case: dict, *, rebalance_max_swaps: int) -> dict:
    loaded = {
        "plan_request": {
            "schema_version": "1.0",
            "request_id": f"realistic-{case['name']}-{rebalance_max_swaps}",
            "generated_at": "2026-01-01T00:00:00Z",
        },
        "global_config": deepcopy(case["global_config"]),
        "subjects": deepcopy(case["subjects"]),
        "calendar_constraints": {"constraints": []},
        "manual_sessions": {"schema_version": "1.0", "manual_sessions": []},
    }
    loaded["global_config"]["rebalance_max_swaps"] = rebalance_max_swaps
    loaded["effective_config"] = resolve_effective_config(loaded, ValidationReport())

    result = run_planner(loaded)
    metrics = collect_metrics(result)
    compact, check_sets = _evaluate_metrics(case, metrics)
    acceptance_checks = check_sets["acceptance_checks"]
    quality_checks = check_sets["quality_checks"]

    return {
        "rebalance_max_swaps": rebalance_max_swaps,
        "accepted_swaps": len(result.get("rebalanced_swaps", [])),
        "metrics": compact,
        "subject_indicators": _subject_indicators(result),
        "acceptance_checks": acceptance_checks,
        "quality_checks": quality_checks,
        "status": "pass" if all(item["status"] == "pass" for item in acceptance_checks.values()) else "fail",
        "quality_status": "pass" if all(item["status"] == "pass" for item in quality_checks.values()) else "fail",
    }


def _run_case(case: dict) -> dict:
    pre = _run_single(case, rebalance_max_swaps=0)
    post = _run_single(case, rebalance_max_swaps=int(case.get("rebalance_max_swaps", 100)))

    return {
        "scenario": case["name"],
        "cross_scenario_role": case.get("cross_scenario_role"),
        "mode": case["global_config"].get("human_distribution_mode", "off"),
        "pre_rebalance": pre,
        "post_rebalance": post,
        "comparison": {
            "humanity_delta": round(post["metrics"]["humanity_score"] - pre["metrics"]["humanity_score"], 4),
            "max_same_subject_streak_days_delta": round(
                post["metrics"]["max_same_subject_streak_days"] - pre["metrics"]["max_same_subject_streak_days"], 4
            ),
            "mono_day_ratio_delta": round(post["metrics"]["mono_day_ratio"] - pre["metrics"]["mono_day_ratio"], 4),
        },
        "status": "pass" if pre["status"] == "pass" and post["status"] == "pass" else "fail",
        "quality_status": "pass" if pre["quality_status"] == "pass" and post["quality_status"] == "pass" else "fail",
    }


def main() -> None:
    cases = [
        {
            "name": "off_monotone",
            "cross_scenario_role": "forward",
            "global_config": {
                "schema_version": "1.0",
                "daily_cap_minutes": 240,
                "daily_cap_tolerance_minutes": 0,
                "subject_buffer_percent": 0.1,
                "critical_but_possible_threshold": 0.8,
                "study_on_exam_day": False,
                "max_subjects_per_day": 3,
                "session_duration_minutes": 30,
                "sleep_hours_per_day": 8,
                "pomodoro_enabled": True,
                "pomodoro_work_minutes": 25,
                "pomodoro_short_break_minutes": 5,
                "pomodoro_long_break_minutes": 15,
                "pomodoro_long_break_every": 4,
                "pomodoro_count_breaks_in_capacity": True,
                "stability_vs_recovery": 0.4,
                "default_strategy_mode": "hybrid",
                "human_distribution_mode": "off",
                "target_daily_subject_variety": 2,
            },
            "subjects": {
                "schema_version": "1.0",
                "subjects": [
                    {"subject_id": "s1", "name": "Core", "cfu": 2.0, "difficulty_coeff": 1, "priority": 3, "completion_initial": 0, "attending": False, "exam_dates": ["2026-01-04"], "selected_exam_date": "2026-01-04", "start_at": "2026-01-01", "end_by": "2026-01-04"},
                    {"subject_id": "s2", "name": "Secondary", "cfu": 0.6, "difficulty_coeff": 1, "priority": 1, "completion_initial": 0, "attending": False, "exam_dates": ["2026-01-04"], "selected_exam_date": "2026-01-04", "start_at": "2026-01-01", "end_by": "2026-01-04"},
                ],
            },
            "acceptance_min_humanity_score": 0.28,
            "acceptance_max_mono_day_ratio": 1.0,
            "acceptance_min_switch_rate": 0.05,
            "acceptance_max_same_subject_streak_days_target": 4,
            "acceptance_min_subject_variety_index": 0.25,
            "quality_min_humanity_score": 0.45,
            "quality_max_mono_day_ratio": 0.9,
            "quality_min_switch_rate": 0.12,
            "quality_max_same_subject_streak_days_target": 3,
            "quality_min_subject_variety_index": 0.4,
            "rebalance_max_swaps": 20,
        },
        {
            "name": "balanced_diffuse",
            "cross_scenario_role": "backward",
            "global_config": {
                "schema_version": "1.0",
                "daily_cap_minutes": 240,
                "daily_cap_tolerance_minutes": 0,
                "subject_buffer_percent": 0.1,
                "critical_but_possible_threshold": 0.8,
                "study_on_exam_day": False,
                "max_subjects_per_day": 3,
                "session_duration_minutes": 30,
                "sleep_hours_per_day": 8,
                "pomodoro_enabled": True,
                "pomodoro_work_minutes": 25,
                "pomodoro_short_break_minutes": 5,
                "pomodoro_long_break_minutes": 15,
                "pomodoro_long_break_every": 4,
                "pomodoro_count_breaks_in_capacity": True,
                "stability_vs_recovery": 0.4,
                "default_strategy_mode": "hybrid",
                "human_distribution_mode": "balanced",
                "concentration_mode": "diffuse",
                "target_daily_subject_variety": 2,
                "max_same_subject_streak_days": 2,
                "max_same_subject_streak_days_target": 2,
                "max_same_subject_consecutive_blocks": 2,
                "human_distribution_strength": 0.35,
            },
            "subjects": {
                "schema_version": "1.0",
                "subjects": [
                    {"subject_id": "s1", "name": "Core", "cfu": 2.0, "difficulty_coeff": 1, "priority": 3, "completion_initial": 0, "attending": False, "exam_dates": ["2026-01-04"], "selected_exam_date": "2026-01-04", "start_at": "2026-01-01", "end_by": "2026-01-04"},
                    {"subject_id": "s2", "name": "Secondary", "cfu": 0.6, "difficulty_coeff": 1, "priority": 1, "completion_initial": 0, "attending": False, "exam_dates": ["2026-01-04"], "selected_exam_date": "2026-01-04", "start_at": "2026-01-01", "end_by": "2026-01-04"},
                ],
            },
            "acceptance_min_humanity_score": 0.50,
            "acceptance_max_mono_day_ratio": 1.0,
            "acceptance_min_switch_rate": 0.1,
            "acceptance_max_same_subject_streak_days_target": 3,
            "acceptance_min_subject_variety_index": 0.5,
            "quality_min_humanity_score": 0.62,
            "quality_max_mono_day_ratio": 0.9,
            "quality_min_switch_rate": 0.18,
            "quality_max_same_subject_streak_days_target": 2,
            "quality_min_subject_variety_index": 0.68,
            "rebalance_max_swaps": 20,
        },
        {
            "name": "subject_overrides_mix",
            "global_config": {
                "schema_version": "1.0",
                "daily_cap_minutes": 240,
                "daily_cap_tolerance_minutes": 0,
                "subject_buffer_percent": 0.1,
                "critical_but_possible_threshold": 0.8,
                "study_on_exam_day": False,
                "max_subjects_per_day": 3,
                "session_duration_minutes": 30,
                "sleep_hours_per_day": 8,
                "pomodoro_enabled": True,
                "pomodoro_work_minutes": 25,
                "pomodoro_short_break_minutes": 5,
                "pomodoro_long_break_minutes": 15,
                "pomodoro_long_break_every": 4,
                "pomodoro_count_breaks_in_capacity": True,
                "stability_vs_recovery": 0.4,
                "default_strategy_mode": "hybrid",
                "human_distribution_mode": "off",
                "concentration_mode": "concentrated",
            },
            "subjects": {
                "schema_version": "1.0",
                "subjects": [
                    {"subject_id": "s_focus", "name": "Focused", "cfu": 0.3, "difficulty_coeff": 1, "priority": 3, "completion_initial": 0, "attending": False, "exam_dates": ["2026-01-06"], "selected_exam_date": "2026-01-06", "start_at": "2026-01-01", "end_by": "2026-01-06", "overrides": {"concentration_mode": "concentrated"}},
                    {"subject_id": "s_spread_a", "name": "Spread A", "cfu": 0.3, "difficulty_coeff": 1, "priority": 3, "completion_initial": 0, "attending": False, "exam_dates": ["2026-01-06"], "selected_exam_date": "2026-01-06", "start_at": "2026-01-01", "end_by": "2026-01-06", "overrides": {"concentration_mode": "diffuse"}},
                    {"subject_id": "s_spread_b", "name": "Spread B", "cfu": 0.3, "difficulty_coeff": 1, "priority": 3, "completion_initial": 0, "attending": False, "exam_dates": ["2026-01-06"], "selected_exam_date": "2026-01-06", "start_at": "2026-01-01", "end_by": "2026-01-06", "overrides": {"concentration_mode": "diffuse"}},
                ],
            },
            "acceptance_min_humanity_score": 0.25,
            "acceptance_max_mono_day_ratio": 1.0,
            "acceptance_min_switch_rate": 0.05,
            "acceptance_max_same_subject_streak_days_target": 6,
            "acceptance_min_subject_variety_index": 0.2,
            "quality_min_humanity_score": 0.5,
            "quality_max_mono_day_ratio": 0.95,
            "quality_min_switch_rate": 0.1,
            "quality_max_same_subject_streak_days_target": 5,
            "quality_min_subject_variety_index": 0.3,
            "rebalance_max_swaps": 20,
        },
    ]

    scenarios = [_run_case(case) for case in cases]
    report = {
        "scenarios": scenarios,
        "summary": {
            "humanity_delta": round(sum(item["comparison"]["humanity_delta"] for item in scenarios), 4),
            "status": "pass" if all(item["status"] == "pass" for item in scenarios) else "fail",
            "quality_status": "pass" if all(item["quality_status"] == "pass" for item in scenarios) else "fail",
            "quality_fail_reasons": _collect_quality_fail_reasons(scenarios),
        },
    }
    comparisons = build_comparisons_report(scenarios, _build_opinion_thresholds())
    _validate_comparisons_consistency(comparisons)
    readme_content = build_results_readme(report, comparisons)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    COMPARISONS_OUT.write_text(json.dumps(comparisons, indent=2), encoding="utf-8")
    README_OUT.write_text(readme_content + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")
    print(f"Wrote {COMPARISONS_OUT}")
    print(f"Wrote {README_OUT}")

    if report["summary"]["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
