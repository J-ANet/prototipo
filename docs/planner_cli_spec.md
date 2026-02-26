# Specifica unica e vincolante — Planner adattivo studio universitario (CLI)

Questa è l'unica specifica normativa del progetto.
Tutti i requisiti qui definiti sono obbligatori: non esistono feature opzionali, non esistono scope ridotti, non esistono elementi di sola rifinitura.

## 1) Obiettivo del prodotto
- Ridurre indecisione quotidiana su cosa studiare.
- Migliorare regolarità e organizzazione fino agli esami.
- Gestire imprevisti con ripianificazione affidabile.
- Generare piani matematicamente corretti e comprensibili.

## 2) Scope del prodotto (completo)
- Interfaccia CLI.
- Motore di pianificazione e ricalcolo deterministico.
- Validatore input no-fail-fast con report completo.
- Input/output JSON con schema versionato.
- Test unitari, integrazione e smoke basati su invarianti.

## 3) Struttura file input
- `plan_request.json`: metadati richiesta + riferimenti ai file input.
- `global_config.json`: configurazione globale planner.
- `subjects.json`: materie e override per materia.
- `calendar_constraints.json`: vincoli esterni e indisponibilità.
- `manual_sessions.json`: sessioni utente (pianificate/svolte) per ricalcolo.

## 4) Default globali
- `daily_cap_minutes`: 180.
- `daily_cap_tolerance_minutes`: 30.
- `subject_buffer_percent`: 0.10.
- `critical_but_possible_threshold`: 0.80.
- `study_on_exam_day`: false.
- `max_subjects_per_day`: 3.
- `sleep_hours_per_day`: 8.
- `session_duration_minutes`: 30.
- `pomodoro_enabled`: true.
- `pomodoro_count_breaks_in_capacity`: true.
- `default_strategy_mode`: `hybrid`.
- `stability_vs_recovery`: 0.4.

### Significato di `stability_vs_recovery`
Parametro in [0,1] che regola il compromesso nei ricalcoli:
- `0.0`: recupero aggressivo.
- `1.0`: stabilità massima.

## 5) Modello dati funzionale

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
- Giorno esame non studiabile per default (configurabile).

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
- senza calendario: stima `attendance_hours_per_cfu` (default 6, range 5–8).

### Ore base
`hours_base = max(0, (hours_theoretical - attendance_discount_hours) * difficulty_coeff * prep_gap_coeff)`

Dove:
- `difficulty_coeff` default 1.0 (mapping: facile 0.90, medio 1.00, difficile 1.10).
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
- `pomodoro_count_breaks_in_capacity=true`: pause incluse nel consumo capacità.
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
- Secondario: distribuire meglio il carico.

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
- `feasibility = clamp(0,1, 1 - over_capacity_minutes_total / max(1, planned_minutes_total))`
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
- `subject_concentration = mean(max_subject_minutes_day / max(1,total_day_minutes))`
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

## 17) Contratto JSON formale
### 17.1 `plan_request.json`
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

### 17.2 `global_config.json`
Campi richiesti: come schema `schema/planner_global_config.schema.json`.

### 17.3 `subjects.json`
Root:
- `schema_version` (string, required)
- `subjects` (array, required, non-empty)

Whitelist `overrides` per materia (schema chiuso):
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

### 17.4 `calendar_constraints.json`
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

### 17.5 `manual_sessions.json`
Campi richiesti: come schema `schema/planner_manual_sessions.schema.json` + regole coerenza stato:
- skipped => actual=0
- done => actual assente o >= planned
- partial => 0 < actual < planned

### 17.6 `plan_output.json`
- `schema_version`, `plan_id`, `generated_at`
- `plan_summary`, `daily_plan`, `metrics`
- `warnings`, `suggestions`, `decision_trace`
- `effective_config`
- `validation_report` (`errors[]`, `infos[]`)

## 18) Catalogo info e errori
### Info codes
- `INFO_DEFAULT_ATTENDANCE_HOURS_PER_CFU_APPLIED`
- `INFO_DEFAULT_START_AT_APPLIED`
- `INFO_DEFAULT_END_BY_APPLIED`
- `INFO_DEFAULT_SELECTED_EXAM_DATE_APPLIED`
- `INFO_CLAMP_STABILITY_APPLIED`
- `INFO_DEFAULT_POMODORO_OVERRIDES_APPLIED`
- `INFO_GENERATED_SESSION_ID`

### Error codes
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

## 19) Regole validazione (obbligatorie)
- Il validatore deve restituire lista completa errori (no first-error-stop).
- Deve includere `infos` su default/clamp applicati.

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

## 20) Casi limite (decisioni)
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

## 21) Decision trace
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

## 22) Principi non negoziabili
- Deterministico (stesso input => stesso output)
- Affidabile e trasparente
- Adattivo ma stabile
- Formalmente corretto e comprensibile

## 23) Testing obbligatorio
### 23.1 Strategia
- TDD: scrivere prima test unitari/funzionali, poi implementazione.
- Funzioni atomiche, piccole e indipendenti.
- Ogni funzione pubblica deve avere test: happy path + edge cases + error path.

### 23.2 Struttura test minima
- `tests/unit/`
  - validazione schema
  - normalizzazione default/override
  - calcolo monte ore
  - calcolo metriche
  - scoring/tie-breaker
- `tests/integration/`
  - pipeline end-to-end su piccoli input
  - replan su update sessioni
- `tests/property/`
  - invarianti: range metriche, no superamento vincoli hard, determinismo

### 23.3 Invarianti minime da testare sempre
1. determinismo: stesso input -> stesso output;
2. metriche clippate in [0,1];
3. rispetto vincoli hard;
4. error aggregation no-fail-fast;
5. coerenza status sessione (`done/skipped/partial`).

### 23.4 Smoke scenarios (non-golden) obbligatori
Scenario 1 — Piano base fattibile:
- output valido rispetto agli schema JSON;
- nessuna sessione oltre `cap+tolleranza`;
- `confidence_score` in [0,1];
- nessun errore in `validation_report.errors`.

Scenario 2 — Buffer non allocabile:
- warning `BUFFER_NOT_ALLOCABLE` presente almeno per una materia;
- copertura base >= soglia critica;
- buffer coverage < 1 per materia coinvolta.

Scenario 3 — Override invalido:
- validatore restituisce `INVALID_OVERRIDE_KEY`;
- include `field_path` e `suggested_fix`.

Scenario 4 — Pomodoro invalido:
- validatore restituisce `INVALID_POMODORO_CONFIG`.

Scenario 5 — Replan con skipped:
- passato non riscritto;
- solo orizzonte futuro ricalcolato;
- `stability_score` in [0,1];
- `decision_trace` non vuoto.

## 24) Artefatti machine-readable
- `schema/planner_plan_request.schema.json`
- `schema/planner_global_config.schema.json`
- `schema/planner_subjects.schema.json`
- `schema/planner_manual_sessions.schema.json`
- `schema/planner_plan_output.schema.json`
- `examples/planner_output.example.json`
