"""Planted-defect benchmark (chunks K2, K2b). Owned by the BENCH agent; written without reading the
checks or fixes, and uses only the public contract (types.py, profile.py).

- shapes.py   exact signed distance functions; analytic bboxes and extreme points
- text.py     word list, deliberate misspellings, DejaVu Sans Bold and its cap-height metric
- bases.py    40 procedural base designs per split and the renderer
- defects.py  the seven families of 03-EVAL section 1, each planting one defect on base art
- labels.py   expected status/fixer per check from ground truth, the 10 % rule, expected outcome
- generate.py plan, build, write PNGs + manifest (`printready bench generate`)
- sheet.py    contact sheet for eyeballing a split

Ground truth: the subject is alpha >= SUBJECT_ALPHA of the PNG itself, except for opaque samples
(background family), whose subject mask is saved next to the PNG as <id>.mask.png.
"""
