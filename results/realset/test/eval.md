# Real set (test): rules vs agent vs Ebin

100 images; 50 of 50 sampled images labelled (pass 1).
Ebin's pass-1 labels: ready_diecut 16, fixable_diecut 6, scene 28, needs_person 0.
28 scenes; shaped-sticker proofs accepted: rules 23 of 23; agent 0 of 0.

## Preregistered

**Verdict: keep_rules.** agent agrees on 0, rules on 29 (margin -29, needs +5); bad fixes agent 0, rules 0; discordant pairs: only agent right 0, only rules right 29
Rule (PREREG): agent becomes the default only if it agrees with Ebin on at least 5 more of the labelled images than rules mode and has no more bad fixes (unacceptable or damaged).

| mode | agree (scene = fixable, PREREG) | agree (scene = needs person) | runs | unacceptable proofs | damaged | cost total | cost / image | time / image |
|---|---|---|---|---|---|---|---|---|
| rules | 29/50 (58%) | 9/50 | 100 | 0 | 0 | $0.2308 | $0.0023 | 7.6 s |
| agent | 0/50 (0%) | 28/50 | 50 | 0 | 0 | $0.0000 | $0.0000 | 1.0 s |

Paired on 50 images (PREREG mapping): both agree 0, only rules 29, only agent 0, neither 21.

**rules** (rows: Ebin's label, columns: rules outcome)

| | ready | fixable | needs_person |
|---|---|---|---|
| ready_diecut | 0 | 13 | 3 |
| fixable_diecut | 0 | 5 | 1 |
| scene | 0 | 24 | 4 |

**agent** (rows: Ebin's label, columns: agent outcome)

| | ready | fixable | needs_person |
|---|---|---|---|
| ready_diecut | 0 | 0 | 16 |
| fixable_diecut | 0 | 0 | 6 |
| scene | 0 | 0 | 28 |

Rules mode on every image, by image model:

| image model | ready | fixable | needs_person |
|---|---|---|---|
| xai:grok-imagine-image | 0 | 46 | 4 |
| xai:grok-imagine-image-2.0 | 0 | 36 | 14 |

## Rerun (PREREG addendum 1)

Runs whose every model call returned HTTP 403 or 429 with zero tokens, re-attempted with the same client, prompts and models; each replaced by its final rerun. rules: 16 listed, 16 attempts, 16 settled, 0 error at deadline, 0 pending, fixed.png same as the original 16, differs 0; agent: 50 listed, 50 attempts, 50 settled, 0 error at deadline, 0 pending.

**Verdict (rerun (PREREG addendum 1)): keep_rules.** agent agrees on 34, rules on 34 (margin +0, needs +5); bad fixes agent 1, rules 1; discordant pairs: only agent right 0, only rules right 0

| mode | agree (scene = fixable, PREREG) | agree (scene = needs person) | runs | unacceptable proofs | damaged | cost total | cost / image | time / image |
|---|---|---|---|---|---|---|---|---|
| rules | 34/50 (68%) | 6/50 | 100 | 1 | 0 | $0.2768 | $0.0028 | 8.2 s |
| agent | 34/50 (68%) | 6/50 | 50 | 1 | 0 | $0.5497 | $0.0110 | 20.0 s |

Paired on 50 images (PREREG mapping): both agree 34, only rules 0, only agent 0, neither 16.

## Two-class view (post hoc, exploratory): does a person need to look?

| numbers | mode | agree (scene = no person, PREREG) | agree (scene = person) |
|---|---|---|---|
| preregistered | rules | 42/50 | 22/50 |
| preregistered | agent | 0/50 | 28/50 |
| rerun (PREREG addendum 1) | rules | 49/50 | 21/50 |
| rerun (PREREG addendum 1) | agent | 49/50 | 21/50 |
