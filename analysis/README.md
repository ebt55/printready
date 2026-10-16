# analysis/: post-hoc, exploratory

**Everything in this folder was decided after Ebin's pass-1 labels were in.** None of it is
preregistered, none of it changes the PREREG keep-or-remove verdict (`printready realset eval`,
`results/realset/test/eval.md`), and it lives outside `src/` so the frozen, hashed code stays
exactly as preregistered.

`posthoc.py` reads committed results and labels only (no API calls):

```
uv run python analysis/posthoc.py --split test [--build-pass2]
```

1. **Integrity checks, to run before pass 2** (PASS/FAIL, exit 1 on any FAIL):
   - every billed rerun attempt (PREREG addendum 1) has its `runs.jsonl` row;
   - runs that share a `fixed.png` sha256 have byte-identical `proof.png`, so pass 2's dedupe by
     fixed hash is a dedupe by the image Ebin sees;
   - the pass-2 list the label page receives (`label-pass2.json` and its PNGs) carries no mode,
     model or original/rerun information.
   `--build-pass2` first writes the pass-2 list with the frozen `printready.realset.label.pass2_items`
   if it is missing (the same files `printready realset label --pass 2` writes).
2. **Views**, for the preregistered runs and with the reruns in place, side by side, written to
   `results/realset/test/posthoc.md`; every table is marked post hoc:
   - product agreement: die-cut / rounded rectangle / needs a person against Ebin's
     ready-or-fixable die-cut / scene / needs a person;
   - the two-class view: does a person need to look (with a scene counted both ways);
   - the ceiling: the generated images are opaque JPEGs, so no run can be `ready`, and the images
     Ebin called ready as a die-cut cap agreement under the PREREG mapping;
   - why runs needed a person, per mode: error, turn limit, budget, the model's own choice, or a rule;
   - three customer messages from each mode for the same images, picked with seed 7.
