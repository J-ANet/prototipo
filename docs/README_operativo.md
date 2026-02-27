# Planner CLI - Guida operativa

Questa guida descrive come usare la CLI Python del planner, i parametri principali di configurazione e come interpretare i warning più comuni.

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

---

## Campi di configurazione: globali e per-subject

Di seguito una tabella operativa con i campi usati dal planner, con default/range e impatto pratico sul motore.

### 1) Campi globali (`global_config.json`)

| Campo | Default | Range / valori | Impatto su planner |
|---|---:|---|---|
| `schema_version` | n/d | string | Versionamento payload. |
| `daily_cap_minutes` | `180` | intero `>=30`, step 15 | Capienza giornaliera base per costruzione slot. |
| `daily_cap_tolerance_minutes` | `30` | intero `>=0` | Tolleranza oltre cap (max giornaliero = cap + tolerance). |
| `subject_buffer_percent` | `0.10` | `[0,1]` | Quota buffer aggiuntiva ore per materia. |
| `critical_but_possible_threshold` | `0.80` | `[0,1]` | Soglia severità fattibilità in warning/suggerimenti. |
| `study_on_exam_day` | `false` | boolean | Se false, evita studio nel giorno d’esame. |
| `max_subjects_per_day` | `3` | intero `>=1` | Vincolo su varietà massima giornaliera; usato anche in rebalance. |
| `session_duration_minutes` | `30` | intero `>=30`, step 15 | Granularità assegnazioni (chunk minimi). |
| `sleep_hours_per_day` | `8` | numero `[0,16]` | Riduce capienza effettiva giornaliera disponibile. |
| `sleep_overrides_by_weekday` | n/d | mappa weekday -> `[0,16]` | Override sonno per giorno settimana. |
| `sleep_overrides_by_date` | n/d | mappa data ISO -> `[0,16]` | Override sonno per singola data. |
| `pomodoro_enabled` | `true` | boolean | Attiva regole pomodoro nel calcolo capacità. |
| `pomodoro_work_minutes` | `25` | intero `>=15` | Durata blocco lavoro pomodoro. |
| `pomodoro_short_break_minutes` | `5` | intero `>=0` | Pausa breve pomodoro. |
| `pomodoro_long_break_minutes` | `15` | intero `>=0` | Pausa lunga pomodoro. |
| `pomodoro_long_break_every` | `4` | intero `>=2` | Frequenza pausa lunga. |
| `pomodoro_count_breaks_in_capacity` | `true` | boolean | Se true, pause consumano capacità giornaliera. |
| `stability_vs_recovery` | `0.4` | clamp in `[0,1]` | Bilanciamento stabilità vs recupero (utile in replan + metriche). |
| `default_strategy_mode` | `hybrid` | `forward/backward/hybrid` | Strategia default usata se materia non ha override `strategy_mode`. |
| `human_distribution_mode` | `off` | `off/balanced/strict` | Soft policy anti-monotonia (penalty + limiti streak/varietà). |
| `max_same_subject_streak_days` | `3` | intero `>=1` | Limite streak giorni consecutivi stessa materia in modalità human distribution. |
| `max_same_subject_consecutive_blocks` | `3` | intero `>=1` | Limite blocchi consecutivi stessa materia nello stesso giorno. |
| `target_daily_subject_variety` | `2` | intero `>=1` | Obiettivo minimo varietà giornaliera (soft penalty se manca). |
| `concentration_mode` *(subject_concentration_mode globale)* | `diffuse` | `diffuse/concentrated` | Bias di concentrazione globale (scoring + preferenza blocchi più concentrati). |
| `humanity_warning_threshold` | `0.45` | `[0,1]` | Soglia warning su metriche umanità piano. |

### 2) Campi per materia (`subjects[].overrides`)

> Gli override sono ammessi solo nelle chiavi consentite dallo schema; chiavi extra producono `INVALID_OVERRIDE_KEY`.

| Campo override | Default effettivo | Range / valori | Impatto su planner |
|---|---:|---|---|
| `subject_buffer_percent` | eredita globale (`0.10`) | `[0,1]` | Modula buffer solo per quella materia. |
| `critical_but_possible_threshold` | eredita globale (`0.80`) | `[0,1]` | Sensibilità warning fattibilità per materia. |
| `strategy_mode` | eredita `default_strategy_mode` (`hybrid`) | `forward/backward/hybrid` | Influenza priorità temporale rispetto alla distanza dall’esame. |
| `stability_vs_recovery` | eredita globale (`0.4`) | clamp `[0,1]` | Peso stabilità/recupero locale in replan. |
| `start_at` | dal subject o default globale/oggi | data ISO | Inizio finestra pianificabile materia (hard). |
| `end_by` | da selected_exam_date o prima exam date | data ISO | Fine finestra pianificabile materia (hard). |
| `max_subjects_per_day` | eredita globale (`3`) | intero `>=1` | Vincolo locale varietà (compatibilità con rebalance). |
| `pomodoro_enabled` | eredita globale (`true`) | boolean | Attiva/disattiva pomodoro per materia. |
| `pomodoro_work_minutes` | eredita globale (`25`) | intero `>=15` | Parametro pomodoro locale. |
| `pomodoro_short_break_minutes` | eredita globale (`5`) | intero `>=0` | Parametro pomodoro locale. |
| `pomodoro_long_break_minutes` | eredita globale (`15`) | intero `>=0` | Parametro pomodoro locale. |
| `pomodoro_long_break_every` | eredita globale (`4`) | intero `>=2` | Parametro pomodoro locale. |
| `pomodoro_count_breaks_in_capacity` | eredita globale (`true`) | boolean | Parametro pomodoro locale. |
| `human_distribution_mode` | eredita globale (`off`) | `off/balanced/strict` | Soft anti-monotonia solo per materia. |
| `max_same_subject_streak_days` | eredita globale (`3`) | intero `>=1` | Limite streak locale materia. |
| `max_same_subject_consecutive_blocks` | eredita globale (`3`) | intero `>=1` | Limite blocchi consecutivi locale materia. |
| `concentration_mode` *(subject_concentration_mode per-subject)* | eredita globale (`diffuse`) | `diffuse/concentrated` | Override concentrazione per singola materia. |

---

## Strategy, concentrazione e rebalance finale

### `default_strategy_mode` + override `strategy_mode`

- `default_strategy_mode` è il fallback globale.
- Se una materia ha `overrides.strategy_mode`, quello ha precedenza.
- Effetti:
  - `forward`: premia lavoro lontano dall’esame.
  - `backward`: premia lavoro vicino all’esame.
  - `hybrid`: neutro con leggero boost in prossimità esame.

### `subject_concentration_mode` globale/per-subject

- Nome tecnico nel JSON: `concentration_mode`.
- Globale (`global_config.concentration_mode`): definisce bias base (`diffuse` o `concentrated`).
- Per-subject (`subjects[].overrides.concentration_mode`): override locale.
- Effetto operativo:
  - in `concentrated` il planner riduce la penalità di concentrazione e aumenta leggermente il punteggio, favorendo blocchi più densi sulla stessa materia;
  - in `diffuse` mantiene comportamento distribuito standard.

### Interazione tra strategy e rebalance finale

- **Prima fase (allocazione)**: strategy/concentration influenzano il ranking dei candidati.
- **Dopo allocazione (rebalance)**: il motore prova swap locali tra materie per migliorare metriche di umanità.
- Il rebalance **non accetta** swap che peggiorano fattibilità oltre tolleranza (vincoli hard: deadline, max materie/giorno, lock/manuale, passato in replan).
- Quindi: strategy decide la forma iniziale del piano, rebalance la rifinisce senza rompere i vincoli di fattibilità.

---

## Hard constraints vs soft optimization

### Hard constraints (non violabili)

- Finestra data materia (`start_at`/`end_by`/date esame).
- Capacità slot giornaliera (cap + tolerance - locked).
- Coerenza schema/validazione tipi, range, enum, date.
- Sessioni manuali lockate (`locked_by_user`/`pinned`) e porzioni di piano preservate in replan.
- Regole di stato manual sessions (`skipped/done/partial`) e coerenza minuti.

### Soft optimization (ottimizzazione, non garanzia assoluta)

- Minimizzare monotonia/streak (`human_distribution_mode`, target varietà).
- Favorire pattern temporale (`strategy_mode`).
- Favorire concentrazione o diffusione (`concentration_mode`).
- Migliorare metriche umanità via rebalance (swap locali benefici).

Se soft e hard entrano in conflitto, prevalgono sempre gli hard constraints.


## Nota audit smoke: interpretazione dei delta

Nel report `results/realistic_smoke/README.md` la sezione **Opinione** è generata in modo data-driven da `results/realistic_smoke/comparisons.json`:

- `abs(humanity_delta) <= 0.1` → impatto **marginale**
- `0.1 < abs(humanity_delta) <= 0.3` → impatto **moderato**
- `abs(humanity_delta) > 0.3` → impatto **forte**

Il testo mostrato per ogni scenario riporta sempre il delta reale (`Δ`) e la direzione (`incremento`, `calo`, `stabile`) derivati dai dati del confronto, senza frasi hardcoded per singolo scenario.

---

## Esempi JSON completi

### A) Piano concentrato

```json
{
  "global_config": {
    "schema_version": "1.0",
    "daily_cap_minutes": 240,
    "daily_cap_tolerance_minutes": 30,
    "subject_buffer_percent": 0.1,
    "critical_but_possible_threshold": 0.8,
    "study_on_exam_day": false,
    "max_subjects_per_day": 2,
    "session_duration_minutes": 30,
    "sleep_hours_per_day": 8,
    "pomodoro_enabled": true,
    "pomodoro_work_minutes": 25,
    "pomodoro_short_break_minutes": 5,
    "pomodoro_long_break_minutes": 15,
    "pomodoro_long_break_every": 4,
    "pomodoro_count_breaks_in_capacity": true,
    "stability_vs_recovery": 0.4,
    "default_strategy_mode": "backward",
    "human_distribution_mode": "off",
    "max_same_subject_streak_days": 3,
    "max_same_subject_consecutive_blocks": 4,
    "target_daily_subject_variety": 1,
    "concentration_mode": "concentrated",
    "humanity_warning_threshold": 0.45
  },
  "subjects": {
    "schema_version": "1.0",
    "subjects": [
      {
        "subject_id": "analisi1",
        "name": "Analisi 1",
        "cfu": 9,
        "difficulty_coeff": 1.2,
        "priority": 4,
        "completion_initial": 0.1,
        "attending": true,
        "exam_dates": ["2026-02-15"]
      },
      {
        "subject_id": "fisica1",
        "name": "Fisica 1",
        "cfu": 6,
        "difficulty_coeff": 1.0,
        "priority": 3,
        "completion_initial": 0.0,
        "attending": false,
        "exam_dates": ["2026-02-20"]
      }
    ]
  }
}
```

### B) Piano diffuso

```json
{
  "global_config": {
    "schema_version": "1.0",
    "daily_cap_minutes": 180,
    "daily_cap_tolerance_minutes": 30,
    "subject_buffer_percent": 0.1,
    "critical_but_possible_threshold": 0.8,
    "study_on_exam_day": false,
    "max_subjects_per_day": 3,
    "session_duration_minutes": 30,
    "sleep_hours_per_day": 8,
    "pomodoro_enabled": true,
    "pomodoro_work_minutes": 25,
    "pomodoro_short_break_minutes": 5,
    "pomodoro_long_break_minutes": 15,
    "pomodoro_long_break_every": 4,
    "pomodoro_count_breaks_in_capacity": true,
    "stability_vs_recovery": 0.4,
    "default_strategy_mode": "forward",
    "human_distribution_mode": "strict",
    "max_same_subject_streak_days": 2,
    "max_same_subject_consecutive_blocks": 2,
    "target_daily_subject_variety": 3,
    "concentration_mode": "diffuse",
    "humanity_warning_threshold": 0.45
  },
  "subjects": {
    "schema_version": "1.0",
    "subjects": [
      {
        "subject_id": "analisi1",
        "name": "Analisi 1",
        "cfu": 9,
        "difficulty_coeff": 1.2,
        "priority": 4,
        "completion_initial": 0.1,
        "attending": true,
        "exam_dates": ["2026-02-15"]
      },
      {
        "subject_id": "fisica1",
        "name": "Fisica 1",
        "cfu": 6,
        "difficulty_coeff": 1.0,
        "priority": 3,
        "completion_initial": 0.0,
        "attending": false,
        "exam_dates": ["2026-02-20"]
      },
      {
        "subject_id": "chimica",
        "name": "Chimica",
        "cfu": 6,
        "difficulty_coeff": 0.9,
        "priority": 2,
        "completion_initial": 0.2,
        "attending": false,
        "exam_dates": ["2026-02-27"]
      }
    ]
  }
}
```

### C) Mix per-subject (override strategy/concentration)

```json
{
  "global_config": {
    "schema_version": "1.0",
    "daily_cap_minutes": 210,
    "daily_cap_tolerance_minutes": 30,
    "subject_buffer_percent": 0.1,
    "critical_but_possible_threshold": 0.8,
    "study_on_exam_day": false,
    "max_subjects_per_day": 3,
    "session_duration_minutes": 30,
    "sleep_hours_per_day": 8,
    "pomodoro_enabled": true,
    "pomodoro_work_minutes": 25,
    "pomodoro_short_break_minutes": 5,
    "pomodoro_long_break_minutes": 15,
    "pomodoro_long_break_every": 4,
    "pomodoro_count_breaks_in_capacity": true,
    "stability_vs_recovery": 0.4,
    "default_strategy_mode": "hybrid",
    "human_distribution_mode": "balanced",
    "max_same_subject_streak_days": 3,
    "max_same_subject_consecutive_blocks": 3,
    "target_daily_subject_variety": 2,
    "concentration_mode": "diffuse",
    "humanity_warning_threshold": 0.45
  },
  "subjects": {
    "schema_version": "1.0",
    "subjects": [
      {
        "subject_id": "analisi1",
        "name": "Analisi 1",
        "cfu": 9,
        "difficulty_coeff": 1.2,
        "priority": 4,
        "completion_initial": 0.1,
        "attending": true,
        "exam_dates": ["2026-02-15"],
        "overrides": {
          "strategy_mode": "backward",
          "concentration_mode": "concentrated"
        }
      },
      {
        "subject_id": "fisica1",
        "name": "Fisica 1",
        "cfu": 6,
        "difficulty_coeff": 1.0,
        "priority": 3,
        "completion_initial": 0.0,
        "attending": false,
        "exam_dates": ["2026-02-20"],
        "overrides": {
          "strategy_mode": "forward",
          "concentration_mode": "diffuse",
          "human_distribution_mode": "strict",
          "max_same_subject_streak_days": 2
        }
      }
    ]
  }
}
```

### D) Scenario con replan + skipped

```json
{
  "plan_request": {
    "schema_version": "1.0",
    "request_id": "req-replan-001",
    "generated_at": "2026-01-20T18:00:00Z",
    "global_config_path": "./input/global_config.json",
    "subjects_path": "./input/subjects.json",
    "calendar_constraints_path": "./input/calendar_constraints.json",
    "manual_sessions_path": "./input/manual_sessions.json",
    "replan_context": {
      "previous_plan_id": "plan-2026-01-18",
      "previous_generated_at": "2026-01-18T08:30:00Z",
      "replan_reason": "unexpected_events",
      "from_date": "2026-01-21"
    }
  },
  "manual_sessions": {
    "schema_version": "1.0",
    "sessions": [
      {
        "session_id": "ms1",
        "date": "2026-01-21",
        "subject_id": "analisi1",
        "planned_minutes": 60,
        "actual_minutes_done": 0,
        "status": "skipped"
      },
      {
        "session_id": "ms2",
        "date": "2026-01-22",
        "subject_id": "fisica1",
        "planned_minutes": 60,
        "actual_minutes_done": 0,
        "status": "skipped"
      }
    ]
  }
}
```

---

## Troubleshooting (casi comuni)

### 1) Piano troppo monotono

Sintomi:
- stessa materia ripetuta per più giorni/blocchi;
- bassa varietà giornaliera.

Azioni consigliate:
- imposta `human_distribution_mode: "balanced"` o `"strict"`;
- riduci `max_same_subject_streak_days`;
- riduci `max_same_subject_consecutive_blocks`;
- aumenta `target_daily_subject_variety`;
- se attivo `concentration_mode: "concentrated"`, valuta `"diffuse"` globale o solo su alcune materie.

### 2) Warning di fattibilità

Sintomi:
- warning “critico ma possibile” o piano parziale.

Cause comuni:
- cap giornaliero troppo basso rispetto al carico;
- finestre temporali (`start_at`/`end_by`) troppo strette;
- molte giornate bloccate da vincoli calendario.

Azioni consigliate:
- aumenta `daily_cap_minutes` o `daily_cap_tolerance_minutes`;
- riduci `subject_buffer_percent` (se eccessivo);
- anticipa `start_at` e/o posticipa `end_by` dove realistico;
- rivedi blocchi calendario non indispensabili.

### 3) Buffer non allocabile

Sintomi:
- minuti buffer residui anche con piano pieno.

Cause comuni:
- poco slack negli slot;
- regola “base prima del buffer” (finché base non completata, buffer non entra);
- vincoli di data vicino all’esame.

Azioni consigliate:
- crea margine (più cap/tolerance o meno blocchi);
- riduci `subject_buffer_percent`;
- usa `strategy_mode: "forward"` su materie con molto base da smaltire presto;
- in replan, verifica che non ci siano troppe sessioni lockate e nessuna capacità nuova.

---

## Soglie testuali report audit realistic smoke

Nel report audit `results/realistic_smoke/README.md` la sezione **Opinione** è classificata in modo data-driven (fonte: `results/realistic_smoke/comparisons.json`) usando `abs(humanity_delta)` con soglie esplicite:

- **marginale**: `abs(delta) <= 0.1499`
- **moderato**: `0.1500 <= abs(delta) <= 0.2999`
- **forte**: `abs(delta) >= 0.3000`

Queste soglie sono validate internamente durante la generazione: se etichetta testuale e delta numerico non sono coerenti, la generazione termina con errore.
