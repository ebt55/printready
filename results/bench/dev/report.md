# Planted-defect benchmark: `dev` split

258 samples, 258 predicted, 0 with errors; run took 34.9 s with 8 workers.
Deterministic checks on the image as given (BEFORE); fix success and outcomes from the whole rules pipeline (AFTER). Vision checks are scored live and are not in this report; agent mode is not run on the benchmark.

## Headline

| check | expected warn/fail | recall (exact status) | detected (any warn/fail) | clean false flags | fixer agreement | disagreements |
|---|---|---|---|---|---|---|
| file | 0 | n/a | n/a | 0/40 | n/a | 0 |
| resolution | 28 | 100.0% | 100.0% | 0/40 | 28/28 | 0 |
| background | 40 | 100.0% | 100.0% | 0/40 | 40/40 | 0 |
| soft_alpha | 16 | 100.0% | 100.0% | 0/40 | 16/16 | 0 |
| edge_crop | 24 | 100.0% | 100.0% | 0/40 | 24/24 | 0 |
| islands | 24 | 100.0% | 100.0% | 0/40 | 24/24 | 0 |

- Clean images with any non-pass check: 0/40 (0.0%).
- Fix success on expected-auto samples: 48/48 (100.0%).
- Outcome agreement: 258/258 (100.0%).

## Confusion matrices (BEFORE)

### file

| expected \ predicted | pass | warn | fail | skip |
|---|---|---|---|---|
| pass | **258** | 0 | 0 | 0 |

### resolution

| expected \ predicted | pass | warn | fail | skip |
|---|---|---|---|---|
| pass | **230** | 0 | 0 | 0 |
| warn | 0 | **14** | 0 | 0 |
| fail | 0 | 0 | **14** | 0 |

Recall by status: warn 14/14, fail 14/14

### background

| expected \ predicted | pass | warn | fail | skip |
|---|---|---|---|---|
| pass | **218** | 0 | 0 | 0 |
| fail | 0 | 0 | **40** | 0 |

Recall by status: fail 40/40

### soft_alpha

| expected \ predicted | pass | warn | fail | skip |
|---|---|---|---|---|
| pass | **202** | 0 | 0 | 0 |
| warn | 0 | **16** | 0 | 0 |
| skip | 0 | 0 | 0 | **40** |

Recall by status: warn 16/16

### edge_crop

| expected \ predicted | pass | warn | fail | skip |
|---|---|---|---|---|
| pass | **194** | 0 | 0 | 0 |
| warn | 0 | **8** | 0 | 0 |
| fail | 0 | 0 | **16** | 0 |
| skip | 0 | 0 | 0 | **40** |

Recall by status: warn 8/8, fail 16/16

### islands

| expected \ predicted | pass | warn | fail | skip |
|---|---|---|---|---|
| pass | **194** | 0 | 0 | 0 |
| fail | 0 | 0 | **24** | 0 |
| skip | 0 | 0 | 0 | **40** |

Recall by status: fail 24/24

## Fix success (whole rules pipeline, expected-auto samples)

Success = final deterministic checks all pass, no damaged step, subject IoU >= 0.98 against ground truth outside a 2 px edge band.

| family | ok / n |
|---|---|
| background | 24/24 |
| islands | 16/16 |
| edge_crop | 8/8 |

## Outcome (expected from labels vs `outcome()` after the rules pipeline)

| expected \ predicted | ready | fixable | needs_person |
|---|---|---|---|
| ready | **126** | 0 | 0 |
| fixable | 0 | **76** | 0 |
| needs_person | 0 | 0 | **56** |

## Final statuses vs `expected_final`

| check | agree |
|---|---|
| file | 258/258 |
| resolution | 258/258 |
| background | 258/258 |
| soft_alpha | 258/258 |
| edge_crop | 258/258 |
| islands | 258/258 |

## Vision (live, text family, xai:grok-4.3, cost $0.1370)

| check | precision | recall | tp | fp | fn | tn | skip | not run |
|---|---|---|---|---|---|---|---|---|
| text_garbled | 100.0% | 87.5% | 14 | 0 | 2 | 32 | 0 | 0 |
| text_small | n/a | 0.0% | 0 | 0 | 8 | 40 | 0 | 0 |

Outcome with the vision findings: 38/48 agree with `outcome_vision`.

Text is small below a cap height of 4.2 pt.

| sample | variant | check | planted (intended) | expected | predicted | model read | model cap_height_frac -> pt | true cap pt |
|---|---|---|---|---|---|---|---|---|
| text-029 | garbled | text_garbled | WELCME (WELCOME) | fail/person | pass | WELCOME -> WELCOME | 0.38 -> 47.92 pt | 18.93 |
| text-030 | garbled | text_garbled | FOERST (FOREST) | fail/person | pass | FOERST -> FOERST | 0.15 -> 30.24 pt | 15.67 |
| text-032 | sized | text_small | BREWERY (BREWERY) | warn/customer | pass | BREWERY -> BREWERY | 0.05 -> 10.08 pt | 2.50 |
| text-033 | sized | text_small | SUMMER (SUMMER) | warn/customer | pass | SUMMER -> SUMMER | 0.07 -> 8.06 pt | 2.50 |
| text-034 | sized | text_small | BOOKS (BOOKS) | warn/customer | pass | BOOKS -> BOOKS | 0.05 -> 10.08 pt | 2.50 |
| text-035 | sized | text_small | COOKIES (COOKIES) | warn/customer | pass | COOKIES -> COOKIES | 0.05 -> 6.65 pt | 2.50 |
| text-036 | sized | text_small | ROCKET (ROCKET) | warn/customer | pass | ROCKET -> ROCKET | 0.06 -> 12.1 pt | 3.00 |
| text-037 | sized | text_small | DONUTS (DONUTS) | warn/customer | pass | DONUTS -> DONUTS | 0.08 -> 8.89 pt | 3.00 |
| text-038 | sized | text_small | ADVENTURE (ADVENTURE) | warn/customer | pass | ADVENTURE -> ADVENTURE | 0.06 -> 12.08 pt | 3.00 |
| text-039 | sized | text_small | TACOS (TACOS) | warn/customer | pass | TACOS -> TACOS | 0.05 -> 10.07 pt | 3.00 |

## Disagreements (BEFORE), by check

None.
