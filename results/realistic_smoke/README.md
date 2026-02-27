# Realistic smoke results

Questo report espone **confidence** e **qualità umana** del piano.

## Metriche chiave
- `confidence_score`: fattibilità complessiva del piano.
- `humanity_score` (0-1): qualità percepita della distribuzione, aggregata da varietà/switch/streak.
- `mono_day_ratio` (0-1): quota di giorni con una sola materia.
- `max_same_subject_streak_days`: massima striscia consecutiva di giorni dominati dalla stessa materia.
- `switch_rate` (0-1): frequenza cambi materia tra blocchi consecutivi.

## Opinione (data-driven da `comparisons.json`)

Soglie `abs(humanity_delta)`:
- `marginale`: `<= 0.1499`
- `moderato`: `0.1500 - 0.2999`
- `forte`: `>= 0.3000`

- **off_monotone**: Impatto marginale (stabile) su humanity_score: Δ=+0.0000.
- **balanced_diffuse**: Impatto marginale (stabile) su humanity_score: Δ=+0.0000.

## Mini-tabella verificabilità (mono_day_ratio)

| Scenario | Mono ratio pre | Mono ratio post |
| --- | ---: | ---: |
| `off_monotone` | 0.5000 | 0.5000 |
| `balanced_diffuse` | 1.0000 | 1.0000 |

## Stato finale
- Summary status: **pass**
- Humanity delta aggregato: `+0.0000`

## Come rigenerare
```bash
python scripts/generate_realistic_smoke.py
```

Output prodotti:
- `results/realistic_smoke/realism_checks.json`
- `results/realistic_smoke/comparisons.json`
