# Smoke scenarios (non-golden)

Questi smoke non confrontano un output statico predefinito (no golden files).
Validano proprietà/invarianti del planner in contesti diversi.

## Principi
- Gli smoke verificano **proprietà** (fattibilità, vincoli, coerenza, warning corretti), non exact match del piano.
- Il planner deve funzionare su input variabili, non ottimizzato “solo per questi casi”.

## Scenario 1 — Piano base fattibile
Input: 2 materie, cap standard, pochi vincoli.
Check:
- output valido rispetto agli schema JSON;
- nessuna sessione oltre `cap+tolleranza`;
- `confidence_score` in [0,1];
- nessun errore in `validation_report.errors`.

## Scenario 2 — Buffer non allocabile
Input: orizzonte corto, base completabile ma poco margine.
Check:
- warning `BUFFER_NOT_ALLOCABLE` presente almeno per una materia;
- copertura base >= soglia critica, buffer coverage < 1 per materia coinvolta.

## Scenario 3 — Override invalido
Input: `subjects.overrides` con chiave non in whitelist.
Check:
- validatore restituisce `INVALID_OVERRIDE_KEY`;
- include `field_path` e `suggested_fix`.

## Scenario 4 — Pomodoro invalido
Input: `pomodoro_long_break_every = 1` o break oltre limiti.
Check:
- validatore restituisce `INVALID_POMODORO_CONFIG`.

## Scenario 5 — Replan con skipped
Input: piano esistente + sessioni saltate + from_date.
Check:
- passato non riscritto;
- solo orizzonte futuro ricalcolato;
- `stability_score` in [0,1];
- `decision_trace` non vuoto.
