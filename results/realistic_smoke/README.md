# Realistic smoke results

Questo report espone **confidence** e **qualità umana** del piano.

## Metriche chiave
- `confidence_score`: fattibilità complessiva del piano.
- `humanity_score` (0-1): qualità percepita della distribuzione, aggregata da varietà/switch/streak.
- `mono_day_ratio` (0-1): quota di giorni con una sola materia.
- `max_same_subject_streak_days`: massima striscia consecutiva di giorni dominati dalla stessa materia.
- `switch_rate` (0-1): frequenza cambi materia tra blocchi consecutivi.

## Come rigenerare
```bash
python scripts/generate_realistic_smoke.py
```

L'output è in `results/realistic_smoke/realism_checks.json` con `status` pass/fail per scenario e per ogni check.
