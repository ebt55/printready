# Preregistration

Ebin Babu Thomas, 17 Oct 2026. Committed before the benchmark test split and the 100 test images exist. `printready bench generate --split test` and `printready realset gen` refuse to run unless this file is committed, unmodified, and its frozen block matches the code, profile, prompts and data on disk. `printready prereg freeze` writes the block; the prose is written by hand.

## Seen so far, used for tuning

Everything below is tuning data, not a result.

- Bench dev split (seed 7), 258 images. The deterministic checks and fixes score 258 of 258 on it, after bugs found on it were fixed.
- Twenty real Grok images from `realset/prompts-dev.txt` (10 prompts, both image models). They tuned the specks rule in background removal, the shape fallback for scenes, the agent prompt and the vision prompt. They are never in the test set and are not labelled.
- Vision experiments on dev (`docs/vision-notes.md`). `text_garbled` stays on. `text_small` is off by default because it flagged about 1 in 5 lettered real images for text that is fine. The frozen block records the switch.
- In the dev agent run of 17 Oct, before the shape fallback existed, the agent handed off 15 of 20 images and rules mode 12. Noted so nobody can say it was learned later.
- With the final code, rules and agent both call all 20 dev images fixable, with the same outcome on every image. The agent costs about five times as much per image ($0.012 against $0.0024) and takes 25 s against 9 s. So on dev the agent has not yet shown it is worth keeping. Also noted in advance.

## Generated after this commit

- Bench test split, seed 8, same generator, families and thresholds, about 258 images. Its manifest is committed when generated and its numbers are the ones reported.
- Real set. The 50 prompts in `realset/prompts.txt`, frozen here, each sent verbatim to `xai:grok-imagine-image` and `xai:grok-imagine-image-2.0`, square, one image per prompt per model. Every image is judged as a 3 in die-cut order. Files are named by content hash, so no name reveals the model.

## Fixed settings

- Vision and agent model `xai:grok-4.3`, temperature 0, agent turn limit 8, images sent to the model at 768 px long side. The frozen block reads these from the code.
- One run per image per mode, no reruns. An API error, a parse failure or the turn limit ends the run as a hand-off with that reason. Nothing is dropped.
- Rules mode runs on all 100 images. Agent mode runs on the 50 images Ebin labels.
- Both modes have the same fix tools, including `fit_shape`, and the same outcome rule. The agent never picks its outcome.
- Spend cap for the whole project is $10, checked before every paid call. The ledger is committed.
- No change to checks, fixes, prompts, profile or thresholds after the test split or the real set is generated. A fix goes in v2 with a new split and a new run.

## Labelling

One labeller, Ebin, by keypress on a local page. The sample is 50 of the 100 images, drawn with seed 7 from the sorted hashes.

- Pass 1 happens right after generation, before any tool has run on these images. Each original is shown by hash, shuffled, with the words "3 in die-cut sticker". The keys record a fact about the art. 1 `ready_diecut`, 2 `fixable_diecut` (flat background, border, size), 3 `scene` (whole-image art with no clean edge to cut around), 4 `needs_person` (garbled text, art cut off, ambiguous). Backspace undoes the last key.
- Mapping, fixed now. `ready_diecut` is ready, `fixable_diecut` is fixable, `needs_person` is needs_person. `scene` is fixable, because the tool offers a rounded-rectangle whole-image sticker. The eval also reports agreement with `scene` mapped to needs_person, so a reader sees how much of the number is this policy.
- Pass 2 happens after both modes have run on the 50. Every distinct fixed proof from either mode is shown as an image only, shuffled, with no mode, findings or message. A proof both modes produced byte for byte is shown once and the label applies to both. Key y means acceptable to send a customer, n means not. A rounded-rectangle proof Ebin would not send counts as an unacceptable fix for that mode.
- Ebin does not open `results/realset/` or `out/` for these images before pass 1 is done.

## Reported, whatever it shows

- Bench test. Per deterministic check, the confusion matrix, recall on fail and warn, and false flags on the 40 clean images. Fixer agreement. Fix success through the whole rules pipeline with the damage guard. Outcome per sample. Precision and recall for `text_garbled`, with `text_small` reported as disabled.
- Real set. Outcome agreement with pass 1 per mode, paired, as 3 by 3 matrices with discordant counts, under both mappings. Unacceptable and damaged fixes per mode. Of the 50, the count per label and how many shaped-sticker proofs Ebin accepted. Over all 100 in rules mode, outcomes by image model. Cost and latency per image per mode.
- Expectation stated in advance. Each deterministic check reaches recall of at least 0.95 and at most 5 % false flags on clean images on the test split. If one does not, the README says which and why. No gate depends on this.

## Keep-or-remove rule for the agent

Agent mode becomes the default only on two conditions, both measured on Ebin's 50. It agrees with pass 1 on at least 5 more images than rules mode, paired, under the `scene` is fixable mapping. And it has no more unacceptable or damaged fixes than rules mode. The bar is strict on purpose. Both modes share the same tools and should differ on 10 to 15 images, so the agent has to win most of the disagreements. Otherwise rules mode stays the default and the README says the agent did not earn its place.

## What this cannot show

- Anything about Sticker Mule's real uploads, their uploader's prompt wrapping or post-processing, their proofing, or their internal artwork scan. The images came from the xAI API with our prompts.
- Print results on paper. Nothing was printed. "Passes" means passes the rules in `docs/rules.md`, which paraphrase public FAQ pages and add conventions marked as such.
- Art other than these two image models and these 50 prompts.
- Agreement with more than one person. There is no inter-rater number.
- Whether the rules are right. On geometric checks the bench is a correctness test of the code, because the generator and the detectors share the rule definitions.

## Addendum 1, 17 Oct 2026, declared before any rerun

The test runs in commit 2804623 hold two infrastructure failures. Rules mode: 16 vision calls got HTTP 429 ("model at capacity") after the client's three retries, no tokens, so `text_garbled` skipped and the outcome fell to needs_person. Agent mode: all 50 runs ended at the first call with HTTP 403 (prepaid credit exhausted), no tokens; the model was never called. Ledger at that point: $4.93 of the $10 cap. Ebin added credit and approved this addendum.

The no-reruns rule was written so that no model output could be selected on. These runs contain none. We re-attempt exactly these 66 runs, listed by hash in `results/realset/test/rerun-list.txt`, and nothing else. A run qualifies only if every model call in its log returned 403 or 429 with zero tokens; the two rules runs that reached the model and flagged garbled text are not listed. Re-attempts use the unchanged client and backoff, repeated until one attempt bills at least one token or until 19 Oct 2026 18:00 IST, whichever is first. The first attempt that reaches the model is final, whatever it returns. Runs still failing at the deadline stay hand-off "error" and are counted. Outputs go to `results/realset/test-rerun/`; the original runs are never overwritten. Both runs are evaluated and reported side by side; every rerun number in the README says "rerun". For the 16 rules runs we report whether `fixed.png` hashes match the original (the pipeline before vision is deterministic). Pass 2 happens once, after the rerun, on distinct proofs from both runs, blinded as preregistered.

Checks, fixes, prompts, profile, thresholds, model ids, turn limit and temperature are unchanged. The only source changes are the rerun gate (`src/printready/realset/rerun.py`, new; `src/printready/commands/realset.py`; `src/printready/realset/evaluate.py`; `src/printready/realset/label.py`) and `src/printready/prereg.py`, which now also leaves the two workbench UI command files (`commands/serve.py`, `commands/site.py`) out of the source hash, as `web/` already was; no run imports them. `printready prereg verify` at this commit, before the re-freeze:

```
prereg verify: MISMATCH
  CHANGED  src/printready/commands/realset.py (source): b3be2058e0ee -> 2db55478818c
  CHANGED  src/printready/prereg.py (source): 1329914daa2e -> af38a427d724
  CHANGED  src/printready/realset/evaluate.py (source): 7c7a8ad9006d -> 187067ad28b4
  CHANGED  src/printready/realset/label.py (source): 30ac2127e8d5 -> 401b829f6422
  NEW      src/printready/realset/rerun.py (source)
```

Every other frozen hash (profile, prompts, checks, fixes, agent, vision, llm, bench) is unchanged. The model id the API returns is logged per call and reported.

<!-- prereg:frozen:start -->
## Frozen artifacts

Written by `printready prereg freeze`, checked by `printready prereg verify`. Do not edit by hand.

```json
{
 "schema": 1,
 "hashing": "sha256 of the file bytes with CRLF normalised to LF",
 "files": {
  "profile": {
   "path": "profiles/stickermule-diecut.yaml",
   "sha256": "e06a2eb630e28cc1036eb55f2bcf1cf723cdfd479cb93a564bf3f691849b9d78"
  },
  "bench manifest (dev)": {
   "path": "data/bench/manifest-dev.jsonl",
   "sha256": "077ef0fc0f7411d0c605a851bf47eb581f5bb5ab9dc22fb01e3c112e3209f0ac"
  },
  "realset prompts (test)": {
   "path": "realset/prompts.txt",
   "sha256": "5bf0d87762eb923265469d2fdb15ff55ba75b57db7d85da91be58df3eb928c47"
  },
  "bench generator: __init__.py": {
   "path": "src/printready/bench/__init__.py",
   "sha256": "334113f627556c9f75c2bf3be896152aa9a2464a022f5ca233a6f9bcdd79b957"
  },
  "bench generator: bases.py": {
   "path": "src/printready/bench/bases.py",
   "sha256": "8680c45161b7b7a23d6d0ef734062f266a67882a7dcc0204c09d1ae5764de1b2"
  },
  "bench generator: defects.py": {
   "path": "src/printready/bench/defects.py",
   "sha256": "47ed583c43a88dfc15719cc06c770f566660974924a426d37e33219bca246099"
  },
  "bench generator: generate.py": {
   "path": "src/printready/bench/generate.py",
   "sha256": "1c5fa8b84a312013ca11c6a556a4f311cf35615ea391793fc764fecae2802bbe"
  },
  "bench generator: labels.py": {
   "path": "src/printready/bench/labels.py",
   "sha256": "6a7dcf7fce3fcf289a3d2e8a57459d0ace8b58490b655f611295769dcc8da26c"
  },
  "bench generator: shapes.py": {
   "path": "src/printready/bench/shapes.py",
   "sha256": "459c3062f76163fe36ac133205132e16259c886877451e6b1ea8558efb7466fa"
  },
  "bench generator: sheet.py": {
   "path": "src/printready/bench/sheet.py",
   "sha256": "4950d07c3d3e06ea70a9e63ff43cba0cacf5ddab67d66b57c9d62d707b689d78"
  },
  "bench generator: text.py": {
   "path": "src/printready/bench/text.py",
   "sha256": "a21fee74e3ced9243b7846c30682fa3ff88bedb13afb99224e580cbd59e05b3b"
  },
  "prompt: agent-system.md": {
   "path": "src/printready/prompts/agent-system.md",
   "sha256": "2190783fa9ea1976b674a20252232dd2d25b23784cf6fc25d0158238ce34f561"
  },
  "prompt: vision-text.md": {
   "path": "src/printready/prompts/vision-text.md",
   "sha256": "7c8c50ba269949f08dde45d6c1915976b14c0c5a9c256b5ca235bdf144fc596e"
  }
 },
 "source": {
  "src/printready/**/*.py (excluding web/, commands/serve.py, commands/site.py)": {
   "sha256": "91b3c2e30cee18ee501dc27dcb9978015fe6ca1cb78e30d5e49747942eaa18b0",
   "count": 59,
   "files": {
    "src/printready/__init__.py": "090233e838b71ad7d599c024567b45bc921f0500ddbca1b067399ca2737781d0",
    "src/printready/agent.py": "8ede8afbc1a37fb9b7e6ce4a5dd0449b6604472339321c67191529c025a94d19",
    "src/printready/bench/__init__.py": "334113f627556c9f75c2bf3be896152aa9a2464a022f5ca233a6f9bcdd79b957",
    "src/printready/bench/bases.py": "8680c45161b7b7a23d6d0ef734062f266a67882a7dcc0204c09d1ae5764de1b2",
    "src/printready/bench/defects.py": "47ed583c43a88dfc15719cc06c770f566660974924a426d37e33219bca246099",
    "src/printready/bench/generate.py": "1c5fa8b84a312013ca11c6a556a4f311cf35615ea391793fc764fecae2802bbe",
    "src/printready/bench/labels.py": "6a7dcf7fce3fcf289a3d2e8a57459d0ace8b58490b655f611295769dcc8da26c",
    "src/printready/bench/report.py": "865cb9b2cc0ce0547840469e06fcb39a298244151ff019968ab5f7051f60d65c",
    "src/printready/bench/run.py": "35f14a5a3156e83222fb50243ed93a7469a4420800792ef130f8073e7cdf09a0",
    "src/printready/bench/shapes.py": "459c3062f76163fe36ac133205132e16259c886877451e6b1ea8558efb7466fa",
    "src/printready/bench/sheet.py": "4950d07c3d3e06ea70a9e63ff43cba0cacf5ddab67d66b57c9d62d707b689d78",
    "src/printready/bench/text.py": "a21fee74e3ced9243b7846c30682fa3ff88bedb13afb99224e580cbd59e05b3b",
    "src/printready/checks/__init__.py": "c9ec9a4386c294d0a286301a0ed8a632b7335057dcda62b651c5644eb48817a8",
    "src/printready/checks/_common.py": "58d7084e2de21693fcee93de274365d31422b69371397b949e01a9eadf7bf139",
    "src/printready/checks/alpha.py": "4e433657c61c9f22667e3f90fa9bec6f9376d62a23dcffc1af1efebd76436581",
    "src/printready/checks/background.py": "bdd900fb2d5fe254d626e28c8536db65fea02e0042230640e64ffb82f04da522",
    "src/printready/checks/edges.py": "d7e00d88e1d91892ad54f995165e3e1d774ac9ece2cdddef90ea3dea1e1f5823",
    "src/printready/checks/file.py": "cecd2d8e31efa6d61cf49ebefffb9e31264d1894ad649b7dabc5d3d3280a7c7a",
    "src/printready/checks/islands.py": "62e71fe469aea2d9bdeb5e7bf6a24f29e68e89cbe14155f8ff9434579b034f62",
    "src/printready/checks/product.py": "4940aa29c7fbd8158da0df13d4a9c3e4e04d5aef9ca1c880d7e71f1968b45ef3",
    "src/printready/checks/resolution.py": "955575b51caac597ca99abd8d694669db8db3d165bc791299f55860ab1936771",
    "src/printready/cli.py": "bbdf0b3701ede80de29bba1d97f784f6beb2914ca2b883b1b60488531327d9b5",
    "src/printready/commands/__init__.py": "83119e471cbc87f88f2a0aa59d1dc507db65920c87c3695c06f1e57a23290bd5",
    "src/printready/commands/bench.py": "115bf119bcb0e6db7ecf8e9797af6d05834b44653c494325b4933fdd5f724c56",
    "src/printready/commands/check.py": "94ce457bbc94ee1393205a3bc5fa3633f154302297a0b2ee3f098b0781950817",
    "src/printready/commands/figures.py": "09cd219c42aa074f38de6fc7ad6c878b62d52ff5c4ef573fbf547bc3e0a19944",
    "src/printready/commands/fix.py": "afed248a3ceb6556026332ab740fd0d2eb0a274da9091fa4bc085b169b494b89",
    "src/printready/commands/mcp.py": "cd9743d85df92fbffd4a4f2fd2ec3b9fa8112f1a926671c77d2b0cd988674d96",
    "src/printready/commands/prereg.py": "4d55f3e76acba67143e2e125cc2f6c9745e878b27499e791df0c9c029bc20332",
    "src/printready/commands/realset.py": "2db55478818cf681f613f6ed1636a75d094bc4c3e0a27a285e595aa4b816227f",
    "src/printready/commands/rules.py": "86d2b573b4802d52ca9f7ccde5f8f4c0c061b28e70f7bb0f37b85248a4f35cab",
    "src/printready/cutline.py": "0b49f9f17e1c5f5349eb157f4bf486c43c8110279d8c58bf8b711cf17cb6662f",
    "src/printready/figures.py": "cbc62b71c72ec3780470d4f3b3ea29591fb64c48d90723f52fd6eb03afbba238",
    "src/printready/fixes/__init__.py": "1f08ad0a14d724b0f41f3af5a453f933a1b317ec63239bcd0268a3aead762cd1",
    "src/printready/fixes/_common.py": "b567b3ad053b660bc5bf2b4b1d74ee6de2cc42ccbd132bacfa7af114096166d3",
    "src/printready/fixes/background.py": "00d2e36a33738b65ed0cdf170583839ff7b8eb5e7ad92bb22e10ab6696b4ca5b",
    "src/printready/fixes/border.py": "87a9abae8a323b32d5542278c17b0ba43afa317b1c6fe8c27800f61a9191696c",
    "src/printready/fixes/pad.py": "2a84748d40e162010f0c9788e7fd0ed51ead82882a3784b13715f3783b96c069",
    "src/printready/fixes/shape.py": "f1423d7ea8f9acd1be855e3ea96b5c8a5c708d0f6d19de31559334e2cdfbc2f3",
    "src/printready/geometry.py": "2ee08d55b4d48a60c8f017f81ccd51251ca89dbd3673efc83a6883b90f689a82",
    "src/printready/guard.py": "e98c0ad35075d9bb8774e45248925bf3375d16ed41b09e32a4787f3754824c5c",
    "src/printready/imageio.py": "eb7fc7770b3af403ce7f8a3a8c134bf5190363282ea6f21228acd74007e5c97e",
    "src/printready/llm.py": "27e2aebcd201660b6d832926622d5b5f652eb1c1816608fa22621ba1d51a585a",
    "src/printready/mcp_server.py": "28c406d280ce7328ba781cd2772d11c348efa2b9791cf525fd150631abb444e9",
    "src/printready/pipeline.py": "62768437133c90ee1773c7c5fe7ff280292da5ae9cc987d95bbaa15585ceda16",
    "src/printready/prereg.py": "af38a427d724684b50f61a9162e5259866d50b225f77928629414d658dbba250",
    "src/printready/profile.py": "72c2540bc26784dd32719d290cf17d131f2f8f9ac241a17bbcbb436018a4ef5d",
    "src/printready/realset/__init__.py": "ff4dbd1db2d40240d3c46e86f62afac021c2e4d242172267f9def3444878f0f5",
    "src/printready/realset/evaluate.py": "187067ad28b4a4e6aefb7dc0c4cf26f77d789363f02595d02eb14fc34ed68f96",
    "src/printready/realset/gen.py": "573bd92a14f537bb600414262a371b657b38fcece5a775040b6690dd06f00223",
    "src/printready/realset/label.py": "401b829f642258f28d1c3d0c6c2d8efa4acdec763ade4fea2a73193d5d4c0398",
    "src/printready/realset/rerun.py": "dc1ba2adb215ed1bf4a00c538ff79e307e38ee89ae233805bc8cbee7132b9452",
    "src/printready/realset/runs.py": "e661fc745c99956f98df5cb551b53fe2e7e59c2c56b8268d35cbcad1cf86c955",
    "src/printready/realset/sheet.py": "964adde9d65dca6005d1876b17ec3e964e9ceac0bcafcc028e793d5b0c3d338e",
    "src/printready/render.py": "2f86dc011f640335c3628391bf5ce07a3c86b249f4229211384cba89c96b7ead",
    "src/printready/reporthtml.py": "d0395817284910cfcbc2d25685bb4df924b9891700225178468ab5d997da0298",
    "src/printready/spend.py": "bcec300bfb8cd944f4707b284b3c22a240a4923362044c5fcfeeccb5fe0048d1",
    "src/printready/types.py": "fef4ffaeec60ee3f9568f77cd5b35a800fc77f89989f3eb3636a574677825c80",
    "src/printready/vision.py": "fea8f19a335986329ed21c562eb11797d20dc8924626bb7a70d466efcca49be1"
   }
  }
 },
 "settings": {
  "vision_and_agent_model": "xai:grok-4.3",
  "bench_vision_model": "xai:grok-4.3",
  "image_models": [
   "xai:grok-imagine-image",
   "xai:grok-imagine-image-2.0"
  ],
  "agent_max_turns": 8,
  "temperature": 0,
  "text_small_default": false,
  "text_small_env": "PRINTREADY_TEXT_SMALL",
  "agent_tools": [
   "check",
   "look",
   "remove_background",
   "pad_canvas",
   "add_border",
   "bridge_islands",
   "fit_shape",
   "read_text",
   "finish",
   "handoff"
  ],
  "fix_tools": [
   "remove_background",
   "pad_canvas",
   "add_border",
   "bridge_islands",
   "fit_shape"
  ]
 }
}
```
<!-- prereg:frozen:end -->
