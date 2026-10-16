# Does a sticker-style prompt prefix stop Grok Imagine from returning scenes?

**Exploratory, post hoc, one model, one prefix; not preregistered.** Decided after the test results were in. Nothing here changes the preregistered numbers.

- Prefix: `Die-cut sticker design, single subject, flat plain white background, no scenery, no shadow: ` + the customer's prompt
- Model: `xai:grok-imagine-image`, one image per prompt, the 50 test prompts; cost $1.00
- Judged by rules mode, deterministic only (no vision call): the product a run ends with is a die-cut (plain background removed) or a whole-image rounded rectangle (`fit_shape`: no plain background, a scene).
- Compared with the same model's unprefixed test images (rules mode, original runs). Text checks are left out on both sides; 2 unprefixed runs had a failed vision call, which does not change their product.

| product (exploratory, post hoc) | unprefixed (test, rules, original runs) | prefixed |
|---|---|---|
| die cut | 10 (20%) | 47 (94%) |
| rounded rect | 39 (78%) | 3 (6%) |
| needs person | 1 (2%) | 0 (0%) |

Per prompt, unprefixed -> prefixed (exploratory, post hoc):

| move | prompts |
|---|---|
| rounded rect -> die cut | 37 |
| die cut -> die cut | 9 |
| rounded rect -> rounded rect | 2 |
| die cut -> rounded rect | 1 |
| needs person -> die cut | 1 |

Resolution at 3 in (exploratory, post hoc): the prefix gives smaller subjects on more white space, so more die-cuts fall under 300 PPI (warn: the customer picks a smaller size; a rounded rectangle uses the whole canvas):

| resolution | unprefixed (test, rules, original runs) | prefixed |
|---|---|---|
| pass | 44 | 9 |
| warn | 5 | 40 |
| fail | 1 | 1 |

Why runs needed a person (non-text findings; exploratory, post hoc):

| side | reasons |
|---|---|
| unprefixed (test, rules, original runs) | edge_crop 1 |
| prefixed | none |

Contact sheet: `contact-sheet.jpg` (original | proof per prompt).
