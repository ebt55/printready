# Real set (test): post-hoc views

**Post hoc, exploratory.** Decided after Ebin's pass-1 labels were in. Nothing on this page is preregistered or changes the PREREG verdict (see eval.md). "with reruns" = the preregistered runs with the PREREG addendum 1 reruns in place of the runs that never reached a model.

## Integrity checks (before pass 2)

- PASS (a) billed attempts have rows: 66 billed attempts, 0 without a runs.jsonl row
- PASS (b) one proof per fixed.png: 55 fixed.png groups, 55 with one proof
- PASS (c) pass-2 list is blind: 55 items, no mode/model/source

## The ceiling (post hoc)

All 100 of 100 generated images are opaque JPEGs, so every run has to remove a background or change the product, and `outcome()` can never return `ready` (0 ready outputs in all runs). Ebin labelled 16 of the 50 sampled images "ready as a die-cut", so under the PREREG mapping no mode can agree on more than **34 of 50**.

## Original runs

Product agreement (post hoc): Ebin's ready/fixable die-cut -> die_cut, scene -> rounded_rect, needs a person -> needs_person; a run's product is its shape unless it needs a person.

| mode | agree | Ebin die_cut: die_cut / rounded_rect / needs_person | Ebin rounded_rect: die_cut / rounded_rect / needs_person | Ebin needs_person: die_cut / rounded_rect / needs_person |
|---|---|---|---|---|
| rules | 37/50 | 14 / 4 / 4 | 1 / 23 / 4 | 0 / 0 / 0 |
| agent | 0/50 | 0 / 0 / 22 | 0 / 0 / 28 | 0 / 0 / 0 |

Two-class view (post hoc): does a person need to look?

| mode | prereg (scene = no person) | scene = person |
|---|---|---|
| rules | 42/50 | 22/50 |
| agent | 0/50 | 28/50 |

Why runs on the sampled images needed a person (post hoc):

| mode | reasons |
|---|---|
| rules | error 7, rule: edge_crop 1 |
| agent | error 50 |

## With reruns

Product agreement (post hoc): Ebin's ready/fixable die-cut -> die_cut, scene -> rounded_rect, needs a person -> needs_person; a run's product is its shape unless it needs a person.

| mode | agree | Ebin die_cut: die_cut / rounded_rect / needs_person | Ebin rounded_rect: die_cut / rounded_rect / needs_person | Ebin needs_person: die_cut / rounded_rect / needs_person |
|---|---|---|---|---|
| rules | 43/50 | 17 / 4 / 1 | 2 / 26 / 0 | 0 / 0 / 0 |
| agent | 43/50 | 17 / 4 / 1 | 2 / 26 / 0 | 0 / 0 / 0 |

Two-class view (post hoc): does a person need to look?

| mode | prereg (scene = no person) | scene = person |
|---|---|---|
| rules | 49/50 | 21/50 |
| agent | 49/50 | 21/50 |

Why runs on the sampled images needed a person (post hoc):

| mode | reasons |
|---|---|
| rules | rule: edge_crop 1 |
| agent | model choice 1 |

## Customer messages, same images (post hoc)

Three sampled images where both modes would send a proof, picked with seed 7, with reruns.

**p21** (Ebin: ready_diecut)

- rules (template): We removed the plain background, added a little space around the edges and added a 0.1 in white border with a cut line. If the proof looks right, approve it to print your 3 in die-cut sticker.
- agent (model): Removed the white background and added a 0.1 in white border. The sticker prints sharp at 3 in. Please approve the proof.

**p36** (Ebin: scene)

- rules (template): This art has no plain background to cut around, so we suggest a 3 in rounded-rectangle sticker of the whole image; or ask a person to cut out part of the art. If the proof looks right, approve it to print your 3 in rounded-rectangle sticker.
- agent (model): Made your pizza mascot a 3 in rounded-rectangle sticker of the whole image (328 PPI). A person can cut out just the slice and text instead. At 3 in this prints sharp. Please approve the proof.

**p48** (Ebin: fixable_diecut)

- rules (template): This art has no plain background to cut around, so we suggest a 3 in rounded-rectangle sticker of the whole image; or ask a person to cut out part of the art. If the proof looks right, approve it to print your 3 in rounded-rectangle sticker.
- agent (model): Made it a 3 in rounded-rectangle sticker of the whole image. A person can cut out part of the art instead if you prefer. Please approve the proof.

