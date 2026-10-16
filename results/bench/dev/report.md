# Planted-defect benchmark: `dev` split

258 samples, 258 predicted, 0 with errors; run took 33.6 s with 8 workers.
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
- Outcome agreement: 250/258 (96.9%).

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
| needs_person | 8 | 0 | **48** |

| sample | parameter | expected | predicted | final non-pass | steps | handoff |
|---|---|---|---|---|---|---|
| soft_alpha-008 | ramp 0.06 in (20 px, shadow) | needs_person | ready | all pass | add_border |  |
| soft_alpha-009 | ramp 0.06 in (21 px, glow) | needs_person | ready | all pass | add_border |  |
| soft_alpha-010 | ramp 0.06 in (21 px, shadow) | needs_person | ready | all pass | add_border |  |
| soft_alpha-011 | ramp 0.06 in (20 px, glow) | needs_person | ready | all pass | add_border |  |
| soft_alpha-012 | ramp 0.06 in (21 px, shadow) | needs_person | ready | all pass | add_border |  |
| soft_alpha-013 | ramp 0.06 in (21 px, glow) | needs_person | ready | all pass | add_border |  |
| soft_alpha-014 | ramp 0.06 in (20 px, shadow) | needs_person | ready | all pass | add_border |  |
| soft_alpha-015 | ramp 0.06 in (21 px, glow) | needs_person | ready | all pass | add_border |  |

## Final statuses vs `expected_final`

| check | agree |
|---|---|
| file | 258/258 |
| resolution | 258/258 |
| background | 258/258 |
| soft_alpha | 250/258 |
| edge_crop | 258/258 |
| islands | 258/258 |

## Disagreements (BEFORE), by check

None.
