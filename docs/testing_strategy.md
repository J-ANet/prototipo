# Note sviluppo e testing

## Approccio consigliato
- TDD: scrivere prima test unitari/funzionali, poi implementazione.
- Testare funzioni atomiche, piccole e indipendenti.
- Evitare file/funzioni enormi: preferire componenti modulari e testabili.
- Ogni funzione pubblica deve avere test dedicati (happy path + edge cases + error path).

## Smoke vs Test suite
- Gli smoke NON sono golden.
- La test suite non deve “copiare” gli smoke: deve validare comportamento delle funzioni interne (validator, normalizer, scheduler, metriche, warnings).

## Struttura test suggerita
- `tests/unit/`
  - validazione schema
  - normalizzazione default/override
  - calcolo monte ore
  - calcolo metriche
  - scoring/tie-breaker
- `tests/integration/`
  - pipeline end-to-end su piccoli input
  - replan su update sessioni
- `tests/property/` (opzionale)
  - invarianti (range metriche, no superamento vincoli hard, determinismo)

## Invarianti minime da testare sempre
1. determinismo: stesso input -> stesso output;
2. metriche clippate in [0,1];
3. rispetto vincoli hard;
4. error aggregation no-fail-fast;
5. coerenza status sessione (`done/skipped/partial`).
