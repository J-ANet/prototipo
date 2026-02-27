# Realistic smoke results

Questo report espone **confidence** e **qualità umana** del piano.

## Metriche chiave
- `confidence_score`: fattibilità complessiva del piano.
- `humanity_score` (0-1): qualità percepita della distribuzione, aggregata da varietà/switch/streak.
- `mono_day_ratio` (0-1): quota di giorni con una sola materia.
- `max_same_subject_streak_days`: massima striscia consecutiva di giorni dominati dalla stessa materia.
- `switch_rate` (0-1): frequenza cambi materia tra blocchi consecutivi.

## Opinione (data-driven da `comparisons.json`)

Soglie `abs(humanity_delta)` usate nell'audit smoke:
- `marginale`: `abs(delta) < 0.1000`
- `moderato`: `0.1000 <= abs(delta) < 0.3000`
- `forte`: `abs(delta) >= 0.3000`

- **off_monotone**: impatto **marginale** (stabile) su humanity_score, con Δ=+0.0000.
- **balanced_diffuse**: impatto **marginale** (stabile) su humanity_score, con Δ=+0.0000.

## Mini-tabella verificabilità (mono_day_ratio)

| Scenario | Mono ratio pre | Mono ratio post |
| --- | ---: | ---: |
| `off_monotone` | 0.5000 | 0.5000 |
| `balanced_diffuse` | 1.0000 | 1.0000 |

## Forward vs Backward

Confronto `backward - forward` tra **balanced_diffuse** e **off_monotone**.

| Metrica | Delta (backward-forward) | Interpretazione |
| --- | ---: | --- |
| `humanity_score` | +0.4077 | vantaggio backward |
| `mono_day_ratio` | +0.5000 | vantaggio forward |
| `max_streak_days` | -2.0000 | vantaggio backward |
| `switch_rate` | +0.0561 | vantaggio backward |

## Stato finale
- Acceptance status (`summary.status`): **pass**
- Quality status (`summary.quality_status`): **fail**
- Humanity delta aggregato: `+0.0000`
- Interpretazione: se acceptance è `pass` ma quality è `fail`, il piano è **pass ma da migliorare**.

## Gate di valutazione
- `acceptance_checks`: requisito minimo di fattibilità (usato per lo stato ufficiale).
- `quality_checks`: target qualitativo più severo, utile per evidenziare margini di miglioramento.
- Il report globale resta basato su acceptance (`summary.status`) e aggiunge `summary.quality_status`.

## Come rigenerare
```bash
python scripts/generate_realistic_smoke.py
```

Output prodotti:
- `results/realistic_smoke/realism_checks.json`
- `results/realistic_smoke/comparisons.json`
