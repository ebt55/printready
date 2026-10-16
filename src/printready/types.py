"""The data contract every module shares: the order (Spec), check results (Finding, Report), the
artwork being fixed (Artwork) and its fix history (Step), fix and run results, and the one
outcome rule that turns a final report into ready / fixable / needs_person.

Units: `Spec.size_in` is the longest side of the finished sticker, border included.
`Artwork.ppi = subject_bbox_long_px / (size_in - 2 * profile.border_in)`, set once when the subject
is first known (or from the full canvas while the image is opaque and unremoved).
`Finding.boxes` are (x0, y0, x1, y1) px in the coordinates of the array passed to run_checks.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Literal, get_args

import numpy as np

from printready.profile import Profile

SUBJECT_ALPHA = 128  # subject = pixels with alpha >= this, once a subject is known

Status = Literal["pass", "warn", "fail", "skip"]
Fixer = Literal["auto", "customer", "person", "none"]  # who can resolve a failed/warned finding
Outcome = Literal["ready", "fixable", "needs_person"]  # the decision per image; also the label set for real images
Mode = Literal["rules", "agent"]

STATUSES: tuple[str, ...] = get_args(Status)
FIXERS: tuple[str, ...] = get_args(Fixer)
OUTCOMES: tuple[str, ...] = get_args(Outcome)
MODES: tuple[str, ...] = get_args(Mode)
PRODUCTS: tuple[str, ...] = ("die_cut",)  # v1 scope

# add_border is standard production, not a correction.
CORRECTIVE_FIXES: tuple[str, ...] = ("remove_background", "bridge_islands", "pad_canvas")

DETERMINISTIC_CHECK_IDS: tuple[str, ...] = (
    "file",
    "resolution",
    "background",
    "soft_alpha",
    "edge_crop",
    "islands",
)
VISION_CHECK_IDS: tuple[str, ...] = ("text_garbled", "text_small")
CHECK_IDS: tuple[str, ...] = DETERMINISTIC_CHECK_IDS + VISION_CHECK_IDS

# Severity order for Report.status(); "skip" is not ranked because it is ignored.
_SEVERITY = {"pass": 0, "warn": 1, "fail": 2}


def _jsonable(value: Any) -> Any:
    """Convert numpy scalars/arrays and tuples to plain JSON types, recursively."""
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


@dataclass(frozen=True)
class Spec:
    """The order: product, finished size (longest side, border included, inches), optional prompt."""

    product: str
    size_in: float
    prompt: str | None = None

    def __post_init__(self) -> None:
        if self.product not in PRODUCTS:
            raise ValueError(f"product must be one of {PRODUCTS}, got {self.product!r}")
        if not self.size_in > 0:
            raise ValueError(f"size_in must be positive, got {self.size_in!r}")

    def to_dict(self) -> dict[str, Any]:
        return {"product": self.product, "size_in": float(self.size_in), "prompt": self.prompt}


@dataclass
class Finding:
    check: str  # one of CHECK_IDS
    status: Status
    message: str  # one plain sentence a customer could read
    measured: dict[str, Any]  # the numbers, e.g. {"ppi": 142.3, "max_size_in_at_target": 1.9}
    fixer: Fixer
    boxes: list[tuple[int, int, int, int]] = field(default_factory=list)  # x0,y0,x1,y1 px

    def __post_init__(self) -> None:
        if self.check not in CHECK_IDS:
            raise ValueError(f"unknown check id {self.check!r}")
        if self.status not in STATUSES:
            raise ValueError(f"unknown status {self.status!r}")
        if self.fixer not in FIXERS:
            raise ValueError(f"unknown fixer {self.fixer!r}")
        boxes = []
        for box in self.boxes:
            if len(box) != 4:
                raise ValueError(f"box must be (x0, y0, x1, y1), got {box!r}")
            boxes.append(tuple(int(v) for v in box))
        self.boxes = boxes

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "status": self.status,
            "message": self.message,
            "measured": _jsonable(self.measured),
            "fixer": self.fixer,
            "boxes": [list(b) for b in self.boxes],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Finding:
        return cls(
            check=data["check"],
            status=data["status"],
            message=data["message"],
            measured=dict(data.get("measured", {})),
            fixer=data["fixer"],
            boxes=[tuple(b) for b in data.get("boxes", [])],
        )


@dataclass
class Report:
    findings: list[Finding]

    def status(self) -> Status:
        """Worst status among findings, ignoring skips. "skip" if nothing was actually checked."""
        ranked = [f.status for f in self.findings if f.status != "skip"]
        if not ranked:
            return "skip"
        return max(ranked, key=_SEVERITY.__getitem__)

    def by_check(self, check: str) -> Finding | None:
        """The first finding for `check`, or None if that check did not report."""
        return next((f for f in self.findings if f.check == check), None)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status(), "findings": [f.to_dict() for f in self.findings]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Report:
        return cls(findings=[Finding.from_dict(f) for f in data.get("findings", [])])


@dataclass
class Step:
    """One entry in Artwork.history: every fix call, applied, refused or reverted."""

    fix: str  # function name, e.g. "remove_background"
    ok: bool  # True only if the fix was applied and kept
    damaged: bool  # True if the damage guard reverted it
    note: str  # one plain sentence
    measured: dict[str, Any] = field(default_factory=dict)  # the fix's own numbers, e.g. {"border_in": 0.18}
    # Damage-guard result for a threshold bar: {"metric", "label", "value", "limit", "passed"}; {} if not run
    guard: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fix": self.fix,
            "ok": self.ok,
            "damaged": self.damaged,
            "note": self.note,
            "measured": _jsonable(self.measured),
            "guard": _jsonable(self.guard),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Step:
        return cls(
            fix=data["fix"],
            ok=bool(data["ok"]),
            damaged=bool(data["damaged"]),
            note=data["note"],
            measured=dict(data.get("measured", {})),
            guard=dict(data.get("guard", {})),
        )


@dataclass
class Artwork:
    """Working state passed through fixes."""

    rgba: np.ndarray  # HxWx4 uint8
    subject: np.ndarray | None  # HxW bool, None while opaque and unremoved
    ppi: float  # set once; see Units
    offset: tuple[int, int] = (0, 0)  # cumulative pad_canvas shift: original (x, y) is now (x+dx, y+dy)
    border_in: float | None = None  # None until a border is added
    cut: np.ndarray | None = None  # HxW bool cut mask, None until built
    history: list[Step] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)  # path, bytes, format; set by load_artwork

    def __post_init__(self) -> None:
        if self.rgba.ndim != 3 or self.rgba.shape[2] != 4 or self.rgba.dtype != np.uint8:
            raise ValueError(f"rgba must be HxWx4 uint8, got {self.rgba.shape} {self.rgba.dtype}")
        for name in ("subject", "cut"):
            mask = getattr(self, name)
            if mask is not None and (mask.shape != self.rgba.shape[:2] or mask.dtype != np.bool_):
                raise ValueError(f"{name} must be HxW bool matching rgba, got {mask.shape} {mask.dtype}")
        if not self.ppi > 0:
            raise ValueError(f"ppi must be positive, got {self.ppi!r}")
        self.offset = (int(self.offset[0]), int(self.offset[1]))

    @property
    def height(self) -> int:
        return int(self.rgba.shape[0])

    @property
    def width(self) -> int:
        return int(self.rgba.shape[1])

    def copy(self) -> Artwork:
        """Deep copy, so a fix can work on its own arrays and the guard can compare before/after."""
        return copy.deepcopy(self)

    def to_dict(self) -> dict[str, Any]:
        """JSON summary. Pixel arrays are excluded; only their sizes are reported."""
        return {
            "width": self.width,
            "height": self.height,
            "ppi": float(self.ppi),
            "offset": list(self.offset),
            "subject_px": None if self.subject is None else int(self.subject.sum()),
            "border_in": self.border_in,
            "cut_px": None if self.cut is None else int(self.cut.sum()),
            "history": [s.to_dict() for s in self.history],
            "meta": _jsonable(self.meta),
        }


@dataclass
class FixResult:
    art: Artwork
    ok: bool
    note: str
    damaged: bool = False
    measured: dict[str, Any] = field(default_factory=dict)  # the fix's own numbers (copied into its Step)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "note": self.note,
            "damaged": self.damaged,
            "measured": _jsonable(self.measured),
            "art": self.art.to_dict(),
        }


@dataclass
class RunResult:
    """What both modes (pipeline.run_rules, agent.run_agent) return for one image.
    pipeline.write_outputs(run, out_dir) needs `spec`; it uses `original` for the overlay and the
    before image (reloading art.meta["path"] if original is None) and the shipped profile if
    `profile` is None."""

    mode: Mode
    art: Artwork | None  # the final Artwork (history holds every Step); None if the file never loaded
    before: Report  # run_checks on the loaded art
    after: Report  # final report: last run_checks (+ vision findings if any); the one outcome() uses
    outcome: Outcome
    customer_message: str
    person_notes: list[str] = field(default_factory=list)
    handoff_reason: str | None = None
    cost_usd: float = 0.0
    outputs: dict[str, str] = field(default_factory=dict)  # output name -> file name in out_dir, e.g. "proof" -> "proof.png"
    spec: Spec | None = None
    profile: Profile | None = None
    original: Artwork | None = None  # the art as loaded, before any fix
    elapsed_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "outcome": self.outcome,
            "handoff_reason": self.handoff_reason,
            "customer_message": self.customer_message,
            "person_notes": list(self.person_notes),
            "cost_usd": float(self.cost_usd),
            "elapsed_s": round(float(self.elapsed_s), 3),
            "spec": self.spec.to_dict() if self.spec is not None else None,
            "profile": self.profile.name if self.profile is not None else None,
            "art": self.art.to_dict() if self.art is not None else None,
            "history": [s.to_dict() for s in self.art.history] if self.art is not None else [],
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "outputs": dict(self.outputs),
        }


def outcome(art: Artwork | None, final: Report, handoff: bool = False) -> Outcome:
    """The ONE outcome rule, used by both modes and by eval.

    needs_person: handoff, or any Step damaged, or any warn/fail in `final` with fixer
        person|none|auto (auto left in the FINAL report means the tool could have fixed it but did
        not, or its fix was refused), or any `skip` in `final` (something could not be verified).
    ready: no successful CORRECTIVE_FIXES step in history and `final` has no warn/fail.
    fixable: otherwise (corrective fixes applied, and/or remaining warn/fail are fixer customer,
        e.g. pick a smaller size).
    `art` may be None when the file never loaded (the `file` fail finding then decides).
    """
    history = art.history if art is not None else []
    flagged = [f for f in final.findings if f.status in ("warn", "fail")]
    if handoff or any(s.damaged for s in history):
        return "needs_person"
    if any(f.fixer in ("person", "none", "auto") for f in flagged):
        return "needs_person"
    if any(f.status == "skip" for f in final.findings):
        return "needs_person"
    corrected = any(s.fix in CORRECTIVE_FIXES and s.ok and not s.damaged for s in history)
    if not corrected and not flagged:
        return "ready"
    return "fixable"
