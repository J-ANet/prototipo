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
