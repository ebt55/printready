"""Damage guard: runs after every fix, in both modes, and is part of the score.

- add_border, bridge_islands, pad_canvas: every subject pixel must stay bit-identical after the
  offset (metric `subject_px_changed`, limit 0).
- remove_background: damage = removed pixels whose CIEDE2000 distance from the background colour
  exceeds 2 x bg_delta_e, over the kept subject area (metric `damage_frac`, limit damage_max_frac).
A damaged fix is reverted and recorded as Step(damaged=True); outcome() then returns needs_person.

Always call fixes through `apply_fix`: it records exactly one Step per call (applied, refused or
reverted) with the fix's measurements and the guard result.
"""

from __future__ import annotations

from typing import Any, Callable

import numpy as np

from printready import fixes
from printready.geometry import delta_e_to, ring_uniformity
from printready.profile import Profile
from printready.types import Artwork, FixResult, Spec, Step

FixFn = Callable[..., FixResult]
FIXES: dict[str, FixFn] = {
    "remove_background": fixes.remove_background,
    "add_border": fixes.add_border,
    "bridge_islands": fixes.bridge_islands,
    "pad_canvas": fixes.pad_canvas,
}
REMOVAL_FIXES = ("remove_background",)


def subject_px_changed(before: Artwork, after: Artwork) -> int:
    """Subject pixels of `before` whose RGBA (or subject membership) differs in `after`, after
    shifting by the change in offset. Pixels shifted off the canvas count as changed."""
    if before.subject is None:
        return 0
    dx, dy = after.offset[0] - before.offset[0], after.offset[1] - before.offset[1]
    ys, xs = np.nonzero(before.subject)
    ys2, xs2 = ys + dy, xs + dx
    inside = (ys2 >= 0) & (ys2 < after.height) & (xs2 >= 0) & (xs2 < after.width)
    changed = int((~inside).sum())
    ys, xs, ys2, xs2 = ys[inside], xs[inside], ys2[inside], xs2[inside]
    differs = np.any(before.rgba[ys, xs] != after.rgba[ys2, xs2], axis=1)
    if after.subject is not None:
        differs |= ~after.subject[ys2, xs2]
    else:
        differs[:] = True
    return changed + int(differs.sum())


def removal_damage(before: Artwork, after: Artwork, profile: Profile) -> dict[str, Any]:
    """Removed pixels far from the background colour, as a fraction of the kept subject."""
    removed = (after.rgba[..., 3] == 0) & (before.rgba[..., 3] > 0)
    bg_lab = ring_uniformity(before.rgba[..., :3], profile.bg_delta_e).lab
    far = 0
    if removed.any():
        distance = delta_e_to(before.rgba[..., :3][removed], bg_lab)
        far = int((distance > 2 * profile.bg_delta_e).sum())
    kept = int(after.subject.sum()) if after.subject is not None else 0
    return {"removed_px": int(removed.sum()), "far_px": far, "kept_px": kept, "frac": far / max(kept, 1)}


def measure(fix_name: str, before: Artwork, after: Artwork, profile: Profile) -> dict[str, Any]:
    """The guard result for one applied fix: {"metric", "label", "value", "limit", "passed", ...}."""
    if fix_name in REMOVAL_FIXES:
        damage = removal_damage(before, after, profile)
        value, limit = round(damage["frac"], 5), profile.damage_max_frac
        return {
            "metric": "damage_frac",
            "label": "removed subject colour",
            "value": value,
            "limit": limit,
            "passed": value <= limit,
            "far_px": damage["far_px"],
            "kept_px": damage["kept_px"],
        }
    value = subject_px_changed(before, after)
    return {"metric": "subject_px_changed", "label": "subject pixels changed", "value": value, "limit": 0, "passed": value == 0}


def apply_fix(fix: str | FixFn, art: Artwork, spec: Spec, profile: Profile, **kwargs: Any) -> FixResult:
    """Run one fix, then the guard, and record one Step.

    Returns a FixResult whose `art` is what to continue with: the fixed art if it was applied, else
    a copy of the input. Either way its history ends with the new Step.
    """
    fn = FIXES[fix] if isinstance(fix, str) else fix
    name = fix if isinstance(fix, str) else fn.__name__
    result = fn(art, spec, profile, **kwargs)
    if not result.ok:
        kept = art.copy()
        kept.history.append(Step(name, ok=False, damaged=False, note=result.note, measured=result.measured))
        return FixResult(kept, ok=False, note=result.note, measured=result.measured)

    guard = measure(name, art, result.art, profile)
    if not guard["passed"]:
        note = f"{result.note} Reverted: the damage guard found {guard['label']} at {guard['value']:g} (limit {guard['limit']:g})."
        kept = art.copy()
        kept.history.append(Step(name, ok=False, damaged=True, note=note, measured=result.measured, guard=guard))
        return FixResult(kept, ok=False, note=note, damaged=True, measured=result.measured)

    fixed = result.art
    fixed.history = [*art.history, Step(name, ok=True, damaged=False, note=result.note, measured=result.measured, guard=guard)]
    return FixResult(fixed, ok=True, note=result.note, measured=result.measured)
