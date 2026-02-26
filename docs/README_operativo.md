# Planner CLI - Guida operativa

Questa guida descrive come usare la CLI Python del planner.

## Requisiti

- Python 3.11+

## Struttura

```text
src/planner/
  cli.py
  io.py
  validation/
  normalization/
  engine/
  metrics/
  reporting/
```

## Esecuzione

### Via modulo

```bash
PYTHONPATH=src python -m planner.cli plan --request plan_request.json --output plan_output.json
```

### Via console script

```bash
planner plan --request plan_request.json --output plan_output.json
```

## Formato minimo `plan_request.json`

```json
{
  "global_config_path": "./input/global_config.json",
  "subjects_path": "./input/subjects.json",
  "calendar_constraints_path": "./input/calendar_constraints.json",
  "manual_sessions_path": "./input/manual_sessions.json"
}
```

I path relativi sono risolti rispetto alla cartella del file request.

## Comportamento errori

In caso di errore di validazione o caricamento file referenziati:
- exit code `2`
- output JSON con `status: "error"` e dettagli (`error.details`)

In caso di successo:
- exit code `0`
- output JSON con `status: "ok"`, `result` e `metrics`

## Distribuzione umana delle materie (soft constraints)

Nel `global_config.json` puoi attivare una distribuzione più equilibrata delle materie:

```json
{
  "schema_version": "1.0",
  "human_distribution_mode": "balanced",
  "max_same_subject_streak_days": 3,
  "target_daily_subject_variety": 2
}
```

Modalità disponibili:
- `off`: comportamento legacy (backward compatible).
- `balanced`: penalità moderata se una materia domina troppi giorni consecutivi.
- `strict`: penalità forte e limiti più stringenti su streak/varietà.

Esempio più restrittivo:

```json
{
  "schema_version": "1.0",
  "human_distribution_mode": "strict",
  "max_same_subject_streak_days": 2,
  "target_daily_subject_variety": 3
}
```

Override per materia (in `subjects.json`, dentro `overrides`) supportati dove sensato:

```json
{
  "subject_id": "analisi1",
  "name": "Analisi 1",
  "cfu": 9,
  "difficulty_coeff": 1.2,
  "priority": 3,
  "completion_initial": 0.1,
  "attending": true,
  "exam_dates": ["2026-02-15"],
  "overrides": {
    "human_distribution_mode": "strict",
    "max_same_subject_streak_days": 1
  }
}
```
