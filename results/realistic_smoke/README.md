# Realistic smoke results

Questo report espone **confidence** e **qualità umana** del piano.

## Metriche chiave
- `confidence_score`: fattibilità complessiva del piano.
- `humanity_score` (0-1): qualità percepita della distribuzione, aggregata da varietà/switch/streak.
- `mono_day_ratio` (0-1): quota di giorni con una sola materia.
- `max_same_subject_streak_days`: massima striscia consecutiva di giorni dominati dalla stessa materia.
- `switch_rate` (0-1): frequenza cambi materia tra blocchi consecutivi.

## Qualità umana
Gli scenari smoke sono valutati in modalità **pre-rebalance** e **post-rebalance** con indicatori quantitativi.

| Indicatore | Soglia pass | Esito fail |
| --- | --- | --- |
| `humanity_score` | `>= 0.30` (off_monotone) / `>= 0.55` (balanced_diffuse) | qualità umana insufficiente |
| `mono_day_ratio` | `<= 1.00` | distribuzione troppo monotona |
| `switch_rate` | `>= 0.05` (off_monotone) / `>= 0.10` (balanced_diffuse) | alternanza materie troppo bassa |
| `max_same_subject_streak_days` | `<= 99` (off_monotone) / `<= 2` (balanced_diffuse) | streak eccessivo |
| `subject_variety_index` | `>= 0.30` (off_monotone) / `>= 0.60` (balanced_diffuse) | varietà insufficiente |

Inoltre il report aggrega `comparison.humanity_delta` (post - pre) per controllare l'impatto del rebalance.

## Come rigenerare
```bash
python scripts/generate_realistic_smoke.py
```

L'output è in `results/realistic_smoke/realism_checks.json` con `status` pass/fail per scenario, per fase (pre/post-rebalance) e per ogni check.
