# Vision text checks: dev experiments (17 Oct 2026)

Two sources, both dev only (the test split and the test real set were not touched), model
`xai:grok-4.3` at temperature 0:
- the **dev bench text family**: 48 images, 16 correctly spelled words, 16 garbled words, 16
  correct words with a cap height of 2.5, 3, 8 or 12 pt at a 3 in order, flat-colour type on badges;
- the **20 real dev images** (Grok image outputs from `realset/prompts-dev.txt`, 11 of them with
  lettering). No labels; judged by eye.

Small text means a cap height under 0.7 x 6 pt = 4.2 pt.

## Bench results

| version | what the model is asked | garbled (recall, false flags) | small text (recall, false flags) | cost |
|---|---|---|---|---|
| v0 (baseline) | read the text, flag garbled, estimate `cap_height_frac` | 14/16, 0/32 | 0/8, 0/40 | $0.137 |
| v1 | letter-exact `seen`, correct `intended`, `broken` glyphs, a `box` per line; code decides garbled and measures height | 11/16, 0/32 | 8/8, 0/40 | $0.140 |
| v2 | v1 plus letters spelled out one by one, plus a `misspelled` flag | 15/16, 0/32 | 5/8 + 3 skips, 0/40 | $0.138 |
| v3 | v2 prompt; measurement only: wider search, line chosen by ink area | (v2) | 8/8, 0/40 on the stored boxes of v1 and v2 | $0 |

- **The model cannot measure small text.** In v0 it put 2.5-3 pt capitals at 6.7-12 pt, so no size number comes from the model any more.
- **It can point, roughly.** From v1 on, the model gives a box per line and code measures the cap height in full-resolution pixels: ink = pixels far from the window's dominant colour, glyphs = connected ink components, the line = the group of similar-height glyphs on one centre line with the most ink, cap height = 90th percentile of their heights. The search window grows (0.35, 1, 2 box heights) because boxes around tiny text can sit a whole box height off. On the bench all 16 sized samples measure within 5 % (2.5 pt reads 2.44-2.54, 12 pt 12.3-12.4). v3 is a replay of real v1/v2 boxes, not a separate live run; `results/bench/dev/report.md` shows v2.
- **Garbled: the model must spell, and code decides.** In v1 the model kept typos in its "correct" spelling (KITEN -> KITEN) and silently fixed others while reading (GROCRY -> GROCERY). v2 asks for the letters one by one and a `misspelled` flag; code calls a line garbled if the spelled letters differ from the intended spelling, a letter is unreadable (`?`), or the model flags a misspelling or broken glyphs. Mixed case and style never count. Still missed: WELCME is read as WELCOME even letter by letter.

## Real Grok images: small text does not hold up

Replaying the boxes from the dev rules run (`results/realset/dev/rules/`) through the same
measurement, on the art exactly as the model saw it:
- With the first line rule (most glyphs), large stylised titles read as 1-3 pt (STAY WILD, MAPLE & MOSS, SALT & PINE, KINDNESS): outlines, stitches and shading break letters into many specks. Choosing the line by ink area fixes most (STAY WILD 27 pt, KINDNESS 25 pt).
- Two of the 11 images with lettering still go wrong: on one the box sits on the character's face, not on the lettering of the cup, and reads 2.1 pt; on an embroidered patch the box sits above the stitched letters and nothing is measurable (a `skip`, which sends the image to a person). No real dev image had text that is actually under 4.2 pt.

**Decision: `text_small` is off by default** (`TEXT_SMALL_DEFAULT = False`;
`PRINTREADY_TEXT_SMALL=1` turns it on, the code path stays). It meets the bench bar (8/8, 0/40),
but on real Grok output it would send about 1 in 5 lettered images to a person for text that is
fine, which is the opposite of its job. `text_garbled` stays on (bench 15/16 with no false flags;
no false flags on the real dev images under v2). Cost of these experiments: $0.279, on the ledger.
