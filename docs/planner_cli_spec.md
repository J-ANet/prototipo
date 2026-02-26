# Decisioni di prodotto – Planner adattivo studio universitario (CLI)

Documento consolidato e revisionato delle decisioni funzionali, dei vincoli e del contratto dati per il prototipo CLI.

## 1) Obiettivo del prodotto
- Ridurre indecisione quotidiana su cosa studiare.
- Migliorare regolarità e organizzazione fino agli esami.
- Gestire imprevisti con ripianificazione affidabile.
- Generare piani matematicamente corretti ma anche “umani”.

## 2) Scope MVP
- Solo CLI.
- Focus su motore di pianificazione/ricalcolo e validatore input.
- Input/output JSON.
- Validazione con smoke scenario-based.

## 3) Struttura file input consigliata
- `plan_request.json`: metadati richiesta + riferimenti ai file input.
- `global_config.json`: configurazione globale planner.
- `subjects.json`: materie e override per materia.
- `calendar_constraints.json`: vincoli esterni e indisponibilità.
- `manual_sessions.json`: sessioni utente (pianificate/svolte) per ricalcolo.

## 4) Default globali concordati
- `daily_cap_minutes`: 180.
- `daily_cap_tolerance_minutes`: 30 (usata per non scartare una sessione quando manca poco spazio, senza superare `cap+tolleranza`).
- `subject_buffer_percent`: 0.10.
- `critical_but_possible_threshold`: 0.80.
- `study_on_exam_day`: false.
- `max_subjects_per_day`: 3.
- `sleep_hours_per_day`: 8.
- `session_duration_minutes` (macro-sessione): 30.
- `pomodoro_enabled`: true.
- `pomodoro_count_breaks_in_capacity`: true.
- `default_strategy_mode`: `hybrid`.
- `stability_vs_recovery`: 0.4.

### Significato di `stability_vs_recovery`
Parametro in [0,1] che regola il compromesso nei ricalcoli:
- `0.0`: recupero aggressivo (molti cambi accettati).
- `1.0`: stabilità massima (pochi cambi).

## 5) Modello dati funzionale (alto livello)

### Materie
Campi chiave per materia:
- `subject_id`, `name`, `cfu`
- `priority`, `difficulty_coeff`, `completion_initial`
- `exam_dates`, `selected_exam_date`
- `start_at`, `end_by`, `strategy_mode`
- `pomodoro_overrides`, `overrides`

### Calendario e vincoli
- Sessioni agnostiche all’orario.
- Vincoli giornalieri/settimanali tramite file calendario.
- Giorno esame di default non studiabile (configurabile).

### Sessioni manuali
- Inseribili in anticipo e on-the-fly.
- Contribuiscono all’avanzamento materia.
- Trattate come vincoli in ricalcolo (`locked_by_user=true` default).

## 6) Gerarchia temporale del piano
- Giornata -> macro-sessioni materia.
- Una macro-sessione materia può aggregare più blocchi.
- Macro-sessione composta da micro-sessioni:
  - pomodoro (`work+break`) se attivo,
  - unità minima fissa se pomodoro disattivo.
- Vincolo: macro-sessione minima 30 minuti.

## 7) Calcolo monte ore

### Formula base
`hours_theoretical = cfu * 25`

### Correzione frequenza
Se materia frequentata:
- con calendario lezioni: sottrazione ore lezioni effettive;
- senza calendario: stima `attendance_hours_per_cfu` (default 6, range consigliato 5–8).

### Ore base
`hours_base = max(0, (hours_theoretical - attendance_discount_hours) * difficulty_coeff * prep_gap_coeff)`

Dove:
- `difficulty_coeff` default 1.0 (mapping consigliato: facile 0.90, medio 1.00, difficile 1.10).
- `prep_gap_coeff = 1 + (1 - completion_initial)`.

### Buffer e target
- `hours_buffer = hours_base * subject_buffer_percent`
- `hours_target = hours_base + hours_buffer`

### Slack globale
Ordine sacrificio in stress:
1. slack globale
2. buffer materia
3. studio base

## 8) Pomodoro e capacità giornaliera
- Parametri pomodoro configurabili globalmente e overrideabili per materia.
- `pomodoro_count_breaks_in_capacity=true` (default): pause incluse nel consumo capacità.
- `pomodoro_count_breaks_in_capacity=false`: capacità usa solo minuti studio.

Formule:
- se true: `capacity_used = sum(study_minutes + allocated_break_minutes)`
- se false: `capacity_used = sum(study_minutes)`

## 9) Sonno e capacità giornaliera
- `sleep_hours_per_day` riduce capacità disponibile.
- Override supportati:
  - `sleep_overrides_by_weekday`
  - `sleep_overrides_by_date`
- Precedenza: `sleep_overrides_by_date` > `sleep_overrides_by_weekday` > `sleep_hours_per_day`.

## 10) Precedenze configurazioni
1. sessione manuale/pinned
2. override per materia
3. configurazione globale
4. default motore

## 11) Stati sessione
- `planned`, `done`, `skipped`, `partial`

Regole:
- `effective_done_minutes = actual_minutes_done`
- `remaining_minutes = planned_minutes - effective_done_minutes`
- se `remaining_minutes <= 0` => `done`
- se `actual_minutes_done = 0` => `skipped`

## 12) Algoritmo di pianificazione (deterministico)
1. Normalizzazione input e applicazione precedenze.
2. Costruzione slot disponibili (cap, tolleranza, sonno, vincoli).
3. Calcolo fabbisogni (`hours_base`, `hours_buffer`, residui).
4. Scoring candidati per slot.
5. Assegnazione iniziale forward con vincoli.
6. Rifinitura pre-esame (senza invertire base->buffer).
7. Riempimento vuoti (buffer poi slack).
8. Produzione report (metriche, warning, suggerimenti, trace).

### Scoring default
`score = w_urgency*urgency + w_priority*priority + w_gap*completion_gap + w_difficulty*difficulty + w_window*window_pressure + w_mode*mode_alignment - w_concentration*concentration_penalty`

Pesi default:
- `w_urgency=0.35`
- `w_priority=0.20`
- `w_gap=0.15`
- `w_difficulty=0.10`
- `w_window=0.10`
- `w_mode=0.05`
- `w_concentration=0.05`

Tie-breaker deterministico:
1. esame più vicino
2. priorità maggiore
3. `subject_id` lessicografico

## 13) Strategie per materia
- `forward`: concentra prima.
- `backward`: concentra vicino a `end_by/esame` senza anticipare buffer rispetto allo studio base.
- `hybrid`: base distribuita, buffer più vicino all’esame.

## 14) Obiettivi ottimizzazione
- Primario: minimizzare rischio ritardo esami.
- Secondario: distribuire meglio il carico su scelta utente.

## 15) Warning obbligatori
1. Sessioni manuali che comprimono capacità futura.
2. Sessioni manuali oltre fabbisogno target materia.
3. Impossibilità di rispettare `end_by`.
4. Saturazione periodica elevata (`weekly_saturation`) su settimane consecutive.
5. Studio base completabile ma buffer non allocabile per mancanza slot.

## 16) Metriche
Tutte normalizzate in [0,1], dove 1 è migliore.

- `coverage_subject = min(1, planned_base_minutes / required_base_minutes)`
- `buffer_coverage_subject = min(1, planned_buffer_minutes / required_buffer_minutes)`
- `feasibility = clamp(1 - over_capacity_minutes_total / max(1, planned_minutes_total))`
- `sat_day = used_capacity_minutes / (cap_minutes + tolerance_minutes)`
- `weekly_saturation = weekly_used_capacity / max(1, weekly_capacity_limit)`
- `saturation_score = 1 - min(1, avg(max(0, weekly_saturation - 1)))`
- `deficit_ratio = max(0, required_base_minutes_until_exam - allocable_minutes_until_exam) / max(1, required_base_minutes_until_exam)`
- `time_pressure = 1 / sqrt(max(1, days_to_exam))`
- `risk_exam = clamp(0,1, 0.7*deficit_ratio + 0.3*time_pressure)`
- `risk_exam_score = 1 - risk_exam`
- `cv = stddev(daily_study_minutes) / max(1, mean(daily_study_minutes))`
- `balance_score = 1 - min(1, cv)`
- `robustness = min(1, free_minutes_next_7_days / max(1, required_base_minutes_next_7_days))`
- `recovery_days = backlog_minutes / max(1, avg_free_minutes_per_day)`
- `recovery_score = 1 - min(1, recovery_days/14)`
- `tolerance_dependency = tolerance_used_minutes / max(1, total_allocated_minutes)`
- `tolerance_dependency_score = 1 - min(1, tolerance_dependency)`
- `subject_concentration = max_subject_minutes_day / max(1, total_day_minutes)`
- `concentration_score = 1 - min(1, subject_concentration)`
- `reallocated_ratio = reallocated_minutes / max(1, previous_plan_minutes)`
- `stability_score = 1 - min(1, reallocated_ratio)`

### Pesi default `confidence_score`
`confidence_score = Σ(weight_i * metric_i)` con somma 1.
- coverage: 0.28
- exam risk: 0.22
- feasibility: 0.12
- stability: 0.10
- robustness: 0.08
- balance: 0.06
- saturation: 0.05
- recovery: 0.04
- tolerance dependency: 0.03
- concentration: 0.02

### Mapping `confidence_level`
- high: `confidence_score >= 0.75`
- medium: `0.55 <= confidence_score < 0.75`
- low: `< 0.55`

### Soglie dinamiche rischio esame
- `days_to_exam > 30`: warning se `risk_exam >= 0.60`
- `14 < days_to_exam <= 30`: warning se `risk_exam >= 0.45`
- `days_to_exam <= 14`: warning se `risk_exam >= 0.30`

### Verifica matematica e correzioni operative
Per evitare effetti distorsivi in implementazione, applicare queste correzioni:

1. **Coverage con denominatore nullo**
   - Se `required_base_minutes == 0`, definire `coverage_subject = 1`.
   - Se `required_buffer_minutes == 0`, definire `buffer_coverage_subject = 1`.

2. **Fattibilità non negativa**
   - `feasibility = clamp(0,1, 1 - over_capacity_minutes_total / max(1, planned_minutes_total))`.

3. **Saturazione con tolleranza inclusa**
   - `weekly_capacity_limit = Σ(cap_day + tolerance_day)`.
   - `weekly_saturation` può superare 1; la metrica usa la parte eccedente (`max(0, x-1)`).

4. **Rischio esame con giorni negativi**
   - usare `days_to_exam = max(1, (exam_date - reference_date).days)`.
   - `reference_date` deve essere esplicito: data ricalcolo o data run.

5. **Bilanciamento con giornate a zero studio**
   - per evitare CV artificiale, calcolare `cv` sui soli giorni pianificabili del periodo.

6. **Concentrazione materia più robusta**
   - usare media dei picchi giornalieri: `subject_concentration = mean(max_subject_minutes_day / max(1,total_day_minutes))`.

7. **Stabilità ricalcolo comparabile**
   - `reallocated_minutes` calcolato solo su orizzonte futuro comune tra piano precedente e nuovo.

8. **Range finali metriche**
   - tutte le metriche devono essere clippate in [0,1] prima della combinazione pesata.

## 17) Pseudocodice fasi programma

```text
MAIN(plan_request_path):
  req = load_json(plan_request_path)
  files = resolve_paths(req)

  raw_global = load_json(files.global_config_path)
  raw_subjects = load_json(files.subjects_path)
  raw_calendar = load_json(files.calendar_constraints_path)
  raw_manual = load_json(files.manual_sessions_path)

  validation = validate_all(raw_global, raw_subjects, raw_calendar, raw_manual)
  if validation.errors not empty:
    return build_validation_failure_output(validation)

  normalized = normalize_inputs(req, raw_global, raw_subjects, raw_calendar, raw_manual)
  # include defaults, overrides precedence, derived fields, generated IDs

  workload = compute_workload_per_subject(normalized)
  # cfu*25, attendance discount, coeffs, buffer, target

  capacity = build_capacity_calendar(normalized)
  # apply sleep precedence (date > weekday > default), caps, tolerance, exam-day policy

  slots = build_slots(capacity, normalized)
  # macro sessions + micro-session constraints (pomodoro/fixed)

  base_plan = assign_sessions_deterministic(slots, workload, normalized)
  # scoring, deterministic tie-breakers, max_subjects_per_day

  refined_plan = pre_exam_refinement(base_plan, workload, normalized)
  # preserve base before buffer, reduce lateness risk

  final_plan = fill_gaps_with_buffer_then_slack(refined_plan, workload)

  metrics = compute_metrics(final_plan, workload, capacity, normalized)
  warnings = compute_warnings(final_plan, workload, metrics)
  suggestions = generate_suggestions(metrics, warnings, normalized)
  trace = build_decision_trace(final_plan)

  return build_plan_output(final_plan, metrics, warnings, suggestions, trace, validation.infos)
```

### Funzioni chiave (pseudocodice sintetico)

```text
validate_all(...):
  errors = []
  infos = []
  run structural checks (required, type, enum, ranges)
  run relational checks (references, unique IDs, date windows)
  run domain checks (pomodoro bounds, step constraints)
  apply clamp rules that are allowed (e.g. stability) and append info
  return {errors, infos}

normalize_inputs(...):
  apply global defaults
  apply per-subject defaults
  enforce precedence: manual > subject override > global > engine default
  derive selected_exam_date when single exam date
  derive start_at/end_by defaults
  return normalized model

compute_workload_per_subject(...):
  for subject in subjects:
    theoretical = cfu * 25
    attendance_discount = lessons_hours OR attendance_hours_per_cfu*cfu
    base = max(0, (theoretical - attendance_discount) * difficulty_coeff * prep_gap_coeff)
    buffer = base * subject_buffer_percent
    target = base + buffer
  return workload map

assign_sessions_deterministic(...):
  for slot in chronological order:
    candidates = feasible subjects for slot
    score each candidate
    pick max score with deterministic tie-breakers
    allocate minutes and update residuals
  return plan

compute_metrics(...):
  compute all raw metrics
  clamp every metric in [0,1]
  confidence_score = weighted sum
  confidence_level from thresholds
  return metrics
```

## 18) Contratto JSON formale

### 18.1 `plan_request.json`
- `schema_version` (string, required)
- `request_id` (string, required)
- `generated_at` (datetime ISO, required)
- `global_config_path` (string, required)
- `subjects_path` (string, required)
- `calendar_constraints_path` (string, required)
- `manual_sessions_path` (string, required)
- `replan_context` (object, optional)

`replan_context` minimo:
- `previous_plan_id`, `previous_generated_at`, `replan_reason`, `from_date`

### 18.2 `global_config.json`
- `schema_version` (string, required)
- `daily_cap_minutes` (int, required, default 180, step 15, min=session_duration)
- `daily_cap_tolerance_minutes` (int, required, default 30, min 0, max < session_duration)
- `subject_buffer_percent` (float, required, default 0.10, [0,1])
- `critical_but_possible_threshold` (float, required, default 0.80, step 0.01, [0,1])
- `study_on_exam_day` (bool, required, default false)
- `max_subjects_per_day` (int, required, default 3, min 1)
- `session_duration_minutes` (int, required, default 30, min 30, max daily_cap, step 15)
- `sleep_hours_per_day` (float, required, default 8, [0,16])
- `sleep_overrides_by_weekday` (object, optional)
- `sleep_overrides_by_date` (object, optional)
- `pomodoro_enabled` (bool, required, default true)
- `pomodoro_work_minutes` (int, required, default 25, min 15, max < session_duration)
- `pomodoro_short_break_minutes` (int, required, max floor(work/4))
- `pomodoro_long_break_minutes` (int, required, max floor(work/2))
- `pomodoro_long_break_every` (int, required, min 2)
- `pomodoro_count_breaks_in_capacity` (bool, required, default true)
- `stability_vs_recovery` (float, required, default 0.4, step 0.1, [0,1], clamp+info)
- `default_strategy_mode` (enum required: `forward|backward|hybrid`, default `hybrid`)

### 18.3 `subjects.json`
Root:
- `schema_version` (string, required)
- `subjects` (array, required, non-empty)

Item `subjects[]`:
- `subject_id` (string, required, unique)
- `name` (string, required)
- `cfu` (number, required, >0)
- `difficulty_coeff` (float, required, default 1.0)
- `priority` (int, required, [1,N])
- `completion_initial` (float, required, [0,1])
- `attending` (bool, required)
- `attendance_hours_per_cfu` (float, optional, default 6 + info)
- `exam_dates` (array date, required, non-empty)
- `selected_exam_date` (required se `exam_dates` >1, altrimenti dedotta)
- `start_at` (optional, default giorno successivo al run)
- `end_by` (optional, default giorno prima esame)
- `strategy_mode` (optional, default globale)
- `pomodoro_overrides` (optional, partial override consentito)
- `overrides` (optional, schema chiuso)

### 18.4 Whitelist `overrides` per materia (schema chiuso)
Chiavi ammesse:
- `subject_buffer_percent`
- `critical_but_possible_threshold`
- `strategy_mode`
- `stability_vs_recovery`
- `start_at`
- `end_by`
- `max_subjects_per_day`
- `pomodoro_enabled`
- `pomodoro_work_minutes`
- `pomodoro_short_break_minutes`
- `pomodoro_long_break_minutes`
- `pomodoro_long_break_every`
- `pomodoro_count_breaks_in_capacity`

Qualsiasi altra chiave => `INVALID_OVERRIDE_KEY`.

### 18.5 `calendar_constraints.json`
Root:
- `schema_version` (required)
- `constraints` (array, required)

Item:
- `constraint_id` (required)
- `date` (optional)
- `weekday` (optional enum `mon..sun`)
- `type` (required enum `blocked|cap_override|category_tag`)
- `blocked_minutes` (required if blocked)
- `cap_override_minutes` (required if cap_override)
- `category` (optional)
- `notes` (optional)

### 18.6 `manual_sessions.json`
Root:
- `schema_version` (required)
- `manual_sessions` (array, required)

Item:
- `session_id` (optional; se assente generato)
- `subject_id` (required, deve esistere)
- `date` (required)
- `planned_minutes` (required, >0)
- `actual_minutes_done` (optional)
- `status` (required enum `planned|done|skipped|partial`)
- `locked_by_user` (required default true)
- `notes` (optional, informativo)

Regole coerenza stato:
- skipped => actual=0
- done => actual assente o >= planned
- partial => 0 < actual < planned

### 18.7 `plan_output.json`
- `schema_version`, `plan_id`, `generated_at`
- `plan_summary`, `daily_plan`, `metrics`
- `warnings`, `suggestions`, `decision_trace`
- `effective_config`
- `validation_report` (`errors[]`, `infos[]`)

## 19) Catalogo info e errori

### 19.1 Info codes
- `INFO_DEFAULT_ATTENDANCE_HOURS_PER_CFU_APPLIED`
- `INFO_DEFAULT_START_AT_APPLIED`
- `INFO_DEFAULT_END_BY_APPLIED`
- `INFO_DEFAULT_SELECTED_EXAM_DATE_APPLIED`
- `INFO_CLAMP_STABILITY_APPLIED`
- `INFO_DEFAULT_POMODORO_OVERRIDES_APPLIED`
- `INFO_GENERATED_SESSION_ID`

Formato info:
- `field_path`, `info_code`, `message`, `applied_value`

### 19.2 Error codes
- `INVALID_SCHEMA_VERSION`
- `MISSING_REQUIRED_FIELD`
- `INVALID_TYPE`
- `OUT_OF_RANGE`
- `INVALID_ENUM_VALUE`
- `INVALID_STEP_VALUE`
- `INVALID_DATE_FORMAT`
- `EMPTY_ARRAY_NOT_ALLOWED`
- `DUPLICATE_SUBJECT_ID`
- `UNKNOWN_SUBJECT_REFERENCE`
- `INVALID_SELECTED_EXAM_DATE`
- `INVALID_DATE_WINDOW`
- `INVALID_OVERRIDE_KEY`
- `INVALID_POMODORO_CONFIG`
- `INVALID_STATUS_MINUTES_COMBINATION`

Formato errore:
- `field_path`, `error_code`, `message`, `suggested_fix`

## 20) Regole validazione (no fail-fast)
- Il validatore deve restituire lista completa errori (no first-error-stop).
- Deve includere anche `infos` su default/clamp applicati.

Regole minime:
1. `daily_cap_minutes >= session_duration_minutes` e step 15.
2. `daily_cap_tolerance_minutes < session_duration_minutes`.
3. `session_duration_minutes` min 30, max `daily_cap_minutes`, step 15.
4. `exam_dates` non vuoto.
5. `subject_id` univoco.
6. `manual_sessions.subject_id` deve esistere in `subjects`.
7. `completion_initial` in [0,1].
8. `priority` fuori range -> errore.
9. `stability_vs_recovery` fuori [0,1] -> clamp + info.
10. vincoli pomodoro invalidi -> errore.

## 21) Esempi JSON (contract tests)

### Esempio A — `global_config.json`
```json
{
  "schema_version": "1.0.0",
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
  "default_strategy_mode": "hybrid"
}
```

### Esempio B — `subjects.json`
```json
{
  "schema_version": "1.0.0",
  "subjects": [
    {
      "subject_id": "alg1",
      "name": "Algebra 1",
      "cfu": 9,
      "difficulty_coeff": 1.1,
      "priority": 1,
      "completion_initial": 0.2,
      "attending": true,
      "exam_dates": ["2026-06-20", "2026-07-05"],
      "selected_exam_date": "2026-06-20",
      "strategy_mode": "hybrid",
      "overrides": {
        "subject_buffer_percent": 0.12,
        "pomodoro_count_breaks_in_capacity": true
      }
    }
  ]
}
```

### Esempio C — `manual_sessions.json`
```json
{
  "schema_version": "1.0.0",
  "manual_sessions": [
    {
      "subject_id": "alg1",
      "date": "2026-05-12",
      "planned_minutes": 60,
      "status": "partial",
      "actual_minutes_done": 35,
      "locked_by_user": true,
      "notes": "Ripasso capitolo 2"
    }
  ]
}
```

### Esempio D — validazione con errori + info
```json
{
  "errors": [
    {
      "field_path": "subjects[0].completion_initial",
      "error_code": "OUT_OF_RANGE",
      "message": "completion_initial must be in [0,1]",
      "suggested_fix": "Use a value between 0.0 and 1.0"
    }
  ],
  "infos": [
    {
      "field_path": "subjects[0].attendance_hours_per_cfu",
      "info_code": "INFO_DEFAULT_ATTENDANCE_HOURS_PER_CFU_APPLIED",
      "message": "Default attendance_hours_per_cfu applied",
      "applied_value": 6
    }
  ]
}
```

### Esempio E — override non ammesso (errore)
```json
{
  "schema_version": "1.0.0",
  "subjects": [
    {
      "subject_id": "ana1",
      "name": "Analisi 1",
      "cfu": 9,
      "difficulty_coeff": 1.0,
      "priority": 1,
      "completion_initial": 0.4,
      "attending": false,
      "exam_dates": ["2026-06-22"],
      "overrides": {
        "unknown_key": 123
      }
    }
  ]
}
```

Output atteso: `INVALID_OVERRIDE_KEY`.

### Esempio F — pomodoro invalido (errore)
```json
{
  "schema_version": "1.0.0",
  "daily_cap_minutes": 180,
  "daily_cap_tolerance_minutes": 30,
  "subject_buffer_percent": 0.1,
  "critical_but_possible_threshold": 0.8,
  "study_on_exam_day": false,
  "max_subjects_per_day": 3,
  "session_duration_minutes": 30,
  "sleep_hours_per_day": 8,
  "pomodoro_enabled": true,
  "pomodoro_work_minutes": 30,
  "pomodoro_short_break_minutes": 10,
  "pomodoro_long_break_minutes": 20,
  "pomodoro_long_break_every": 1,
  "pomodoro_count_breaks_in_capacity": true,
  "stability_vs_recovery": 0.4,
  "default_strategy_mode": "hybrid"
}
```

Output atteso: `INVALID_POMODORO_CONFIG`.

## 22) Casi limite (decisioni)
1. `start_at > end_by` => ERROR
2. `selected_exam_date` non in `exam_dates` => ERROR
3. `completion_initial` fuori [0,1] => ERROR
4. `daily_cap_minutes <= 0` => ERROR
5. sessioni manuali sovrapposte: non applicabile (slot agnostici ad orario)
6. nessuno slot valido in finestra materia => WARN + piano parziale
7. session duration > cap => ERROR
8. tutti i giorni bloccati => WARN + piano migliore possibile
9. materia oltre 100% per manual sessions => WARN
10. replan con solo skipped e nessuno slot nuovo => WARN critico

## 23) Suggerimenti automatici (trade-off)
1. aumentare cap giornaliero
2. aumentare tolleranza
3. ridurre buffer percentuale
4. spostare esame a data alternativa
5. passare backward -> hybrid
6. ridurre max materie/giorno
7. aumentare max materie/giorno
8. abbassare stability verso recupero
9. alzare stability verso stabilità

## 24) Decision trace consigliato
Per ogni assegnazione:
- `decision_id`
- `timestamp`
- `slot_id`
- `candidate_subjects[]`
- `scores_by_subject`
- `selected_subject_id`
- `applied_rules[]`
- `blocked_constraints[]`
- `tradeoff_note`
- `confidence_impact`

## 25) Principi non negoziabili
- Deterministico (stesso input => stesso output)
- Affidabile e trasparente
- Adattivo ma stabile
- Umano oltre che formalmente corretto

## 26) Artefatti machine-readable e note sviluppo
- Schema machine-readable JSON disponibili in `schema/`:
  - `planner_plan_request.schema.json`
  - `planner_global_config.schema.json`
  - `planner_subjects.schema.json`
  - `planner_manual_sessions.schema.json`
  - `planner_plan_output.schema.json`
- Esempio output completo disponibile in `examples/planner_output.example.json`.
- Smoke test non-golden e invarianti in `smoke/non_golden_smoke_scenarios.md`.
- Linee guida TDD e modularità testabile in `docs/testing_strategy.md`.

### Altri suggerimenti pratici
1. introdurre validazione schema automatica in CI (prima degli integration test);
2. aggiungere test di determinismo con hash dell'output su input fisso;
3. separare nettamente `validator`, `normalizer`, `scheduler`, `metrics`, `reporter`;
4. versionare schema (`schema_version`) con changelog compatibilità;
5. creare un generatore di dataset random per test property-based (invarianti, no golden).
