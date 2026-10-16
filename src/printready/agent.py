"""Agent mode: a plain tool-use loop over the same deterministic tools rules mode uses.

    messages = [system, user(order + check report)]
    for turn in 1..MAX_TURNS:
        response = client.chat(messages, TOOLS)      # BudgetExceeded / LLMError end the run
        run each tool call in order -> one tool message per call
        images from `look` -> ONE user message after the tool messages
                              (OpenAI-compatible APIs take no images in tool messages)
        stop on finish or handoff
    no finish or handoff -> handoff "turn limit"

The model never picks the outcome: types.outcome() computes it from the art's history, a final
run_checks plus the read_text findings, and whether the run handed off. Pixels change only
inside the fix tools, and every fix runs under the damage guard (guard.apply_fix). Every model
call and every turn is written to log.jsonl before the run moves on. One run, temperature 0,
no reruns.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from PIL import Image

from printready import guard, pipeline, vision
from printready.checks import load_failure_report, run_checks
from printready.imageio import ImageLoadError, load_artwork, save_png
from printready.llm import ChatClient, LLMError, image_part, prepare_image
from printready.profile import RULE_KEYS, Profile
from printready.render import render_overlay, render_proof
from printready.spend import BudgetExceeded
from printready.types import Artwork, Finding, Report, RunResult, Spec, Step, outcome

MAX_TURNS = 8
MAX_MESSAGE_WORDS = 80
LOG_NAME = "log.jsonl"
PROMPT_PATH = Path(__file__).parent / "prompts" / "agent-system.md"
FIX_TOOLS = ("remove_background", "pad_canvas", "add_border", "bridge_islands", "fit_shape")
NUDGE = "Text replies reach nobody. Call a tool; end the run with finish (with the customer message) or handoff."
LAST_TURN = "This is your last turn: call finish or handoff now."
AFTER_IMAGE = ("That is the image you asked for. Reply with tool calls only, not text: "
               "check, a fix, finish (it carries the customer message) or handoff.")

Event = dict[str, Any]
EventFn = Callable[[Event], None]


# ---------------------------------------------------------------- tool schema

def _tool(name: str, description: str, properties: dict[str, Any] | None = None) -> dict[str, Any]:
    props = properties or {}
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": props, "required": list(props)},
        },
    }


TOOLS: list[dict[str, Any]] = [
    _tool("check", "Run the deterministic checks on the current art and return every finding."),
    _tool(
        "look",
        "Render the current art and show it to you as an image in the next message.",
        {"view": {
            "type": "string",
            "enum": ["proof", "overlay"],
            "description": "proof: the sticker with its white border and magenta cut line, as the customer "
                           "will see it; overlay: the art with boxes around flagged findings.",
        }},
    ),
    _tool("remove_background", "Remove a solid one-colour background (background fail, fixer auto). "
                               "Refused for gradients, textures and photos."),
    _tool("pad_canvas", "Add a transparent margin so the border fits inside the canvas (edge_crop warn)."),
    _tool("add_border", "Add the standard white border and build the die-cut line. Required before finish."),
    _tool("bridge_islands", "Grow the border, up to the profile's limit, so separate parts join into one "
                            "sticker (islands fail, fixer auto)."),
    _tool("fit_shape", "Make the order a whole-image rounded-rectangle sticker with its own cut line (for a scene "
                       "with no flat background, or when remove_background is refused). No pixel changes; "
                       "no add_border after it."),
    _tool("read_text", "Read the text in the art with a vision model: is it garbled, and is it big enough "
                       "to print at this size. One extra model call."),
    _tool(
        "finish",
        "End the run: the proof can go to the customer. Needs a cut line first (add_border, or fit_shape).",
        {"customer_message": {"type": "string", "description": "Under 80 words, plain, ends with one approve line."}},
    ),
    _tool(
        "handoff",
        "End the run and send the artwork to a person.",
        {
            "reason": {"type": "string", "description": "A few words, e.g. 'garbled text' or 'gradient background'."},
            "person_notes": {"type": "string", "description": "What the person should look at, and why."},
        },
    ),
]
TOOL_NAMES = tuple(t["function"]["name"] for t in TOOLS)


# ---------------------------------------------------------------- small records

@dataclass
class End:
    """How the run ended. Only `handoff` feeds outcome(); the outcome itself is never the model's."""

    handoff: bool
    reason: str | None  # handoff reason; "error", "turn limit" or "budget" when the loop stopped it
    draft_message: str | None = None  # the model's customer message (finish only)
    person_notes: list[str] = field(default_factory=list)


@dataclass
class ToolResult:
    """One tool call's result: the JSON the model gets back, a short summary for the trace, and
    (look only) the image to show the model and the file it was saved to."""

    content: dict[str, Any]
    summary: str
    image: Image.Image | None = None
    image_file: str | None = None


def _error(message: str, summary: str) -> ToolResult:
    return ToolResult({"ok": False, "error": message}, summary)


def _auto_end(reason: str, detail: str) -> End:
    """The loop, not the model, ended the run: always a handoff."""
    return End(handoff=True, reason=reason, person_notes=[f"The agent run stopped ({reason}): {detail}"])


class _Log:
    """log.jsonl in the run directory: one JSON object per line, written as it happens."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.write_text("", encoding="utf-8")

    def write(self, entry: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")


# ---------------------------------------------------------------- prompts

RULE_LINES: tuple[tuple[str, str], ...] = (
    ("ppi_target", "Resolution: {ppi_target:g} PPI or more at the ordered size."),
    ("ppi_floor", "Below {ppi_floor:g} PPI a print looks visibly soft."),
    ("border_in", "Border: {border_in:g} in of white around the art (narrowest {border_min_in:g} in)."),
    ("min_text_pt", "Text: {min_text_pt:g} pt or larger."),
    ("cap_height_ratio", "Capital letters are about {cap_height_ratio:g} of the point size."),
    ("min_line_pt", "Lines: {min_line_pt:g} pt or thicker (reported, not checked)."),
    ("bg_ring_uniform_frac", "A background is one solid colour, and removable, when {uniform_pct:g} % of the edge "
                             "ring is within {bg_delta_e:g} CIEDE2000 of one colour."),
    ("soft_alpha_max_in", "A soft shadow or glow wider than {soft_alpha_max_in:g} in leaves the cut position unclear."),
    ("edge_cut_min_run_in", "Art running along the canvas edge for more than {edge_cut_min_run_in:g} in is cut off."),
    ("max_bridge_border_in", "Separate parts can be joined by growing the border up to {max_bridge_border_in:g} in."),
    ("bleed_in", "A rounded-rectangle sticker is the whole image, cut {bleed_in:g} in inside its edge."),
    ("shape_corner_radius_in", "Its corners are rounded with a {shape_corner_radius_in:g} in radius."),
)


def _source_tag(source: str) -> str:
    if source == "convention":
        return "[convention]"
    host = urlparse(source).netloc.removeprefix("www.")
    return "[Sticker Mule FAQ]" if host == "stickermule.com" else f"[{host}]"


def system_prompt(profile: Profile, max_turns: int = MAX_TURNS) -> str:
    """agent-system.md with the profile's rules (value + source tag) filled in."""
    values = {k: getattr(profile, k) for k in RULE_KEYS}
    values["uniform_pct"] = round(profile.bg_ring_uniform_frac * 100, 1)
    rules = "\n".join(
        f"- {text.format(**values)} {_source_tag(profile.sources.get(key, 'convention'))}" for key, text in RULE_LINES
    )
    template = PROMPT_PATH.read_text(encoding="utf-8")
    return (template.replace("$profile_name", profile.name).replace("$rules", rules)
            .replace("$border_in", f"{profile.border_in:g}").replace("$max_turns", str(max_turns)))


def first_message(path: Path, art: Artwork, spec: Spec, report: Report) -> str:
    lines = [
        f"Artwork: {path.name}, {art.width} x {art.height} px.",
        f"Order: {spec.size_in:g} in die-cut sticker (longest side, border included).",
    ]
    if spec.prompt:
        lines.append(f"The customer's request: {json.dumps(spec.prompt)}")
    lines += ["Check report on the uploaded file:", json.dumps(_findings_for_model(report.findings)),
              "The uploaded image follows (downscaled to 768 px for you)."]
    return "\n".join(lines)


def _findings_for_model(findings: list[Finding]) -> list[dict[str, Any]]:
    keys = ("check", "status", "fixer", "message", "measured")
    return [{k: f.to_dict()[k] for k in keys} for f in findings]


def _summary(findings: list[Finding]) -> str:
    flagged = [f"{f.status} {f.check}" for f in findings if f.status != "pass"]
    return ", ".join(flagged) if flagged else "all pass"


def _parsed(raw: str) -> Any:
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return raw


# ---------------------------------------------------------------- one run

class _Run:
    """One agent run: its state, its tools and its loop. Only the fix tools replace `self.art`."""

    def __init__(self, art: Artwork, spec: Spec, profile: Profile, out_dir: Path, client: ChatClient,
                 emit: EventFn, log: _Log) -> None:
        self.art, self.spec, self.profile, self.out_dir = art, spec, profile, out_dir
        self.client, self.emit, self.log = client, emit, log
        self.text_findings: list[Finding] = []  # latest read_text answer; part of the final report
        self.end: End | None = None
        self.cost_usd = 0.0  # every model call in this run, read_text included
        self.outputs: dict[str, str] = {"log": LOG_NAME}  # files this run writes; write_outputs keeps them
        self.looks = 0

    # -- the loop ------------------------------------------------------------

    def converse(self, path: Path, before: Report, max_turns: int) -> End:
        """Start the conversation (the order, the check report and the uploaded art) and run it."""
        system = system_prompt(self.profile, max_turns)
        upload_file, upload = self._save_seen(self.art.rgba, "look-0", "upload")
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": [{"type": "text", "text": first_message(path, self.art, self.spec, before)},
                                         image_part(upload)]},
        ]
        self.log.write({"type": "start", "file": path.name, "spec": self.spec.to_dict(), "model": self.client.model,
                        "max_turns": max_turns, "tools": list(TOOL_NAMES), "system_prompt": system,
                        "image": upload_file})
        with self.client.listening(self.on_call):
            return self.loop(messages, max_turns)

    def on_call(self, rec: dict[str, Any]) -> None:
        """Every model call's record, written to the log before its result is used."""
        self.cost_usd += float(rec.get("cost_usd", 0.0))
        self.log.write({"type": "call", **rec})

    def loop(self, messages: list[dict[str, Any]], max_turns: int) -> End:
        """Call the model, run its tools, repeat. Model and budget errors end the run as a
        handoff; they are never raised and never retried here."""
        for n in range(1, max_turns + 1):
            if n == max_turns:
                messages.append({"role": "user", "content": LAST_TURN})
            try:
                resp = self.client.chat(messages, tools=TOOLS, purpose="agent")
            except (BudgetExceeded, LLMError) as exc:
                reason = "budget" if isinstance(exc, BudgetExceeded) else "error"
                self._turn_event({"n": n, "text": "", "tool_calls": [], "tokens": None, "cost_usd": 0.0,
                                  "latency_ms": None, "image": None, "error": f"{reason}: {exc}"})
                return _auto_end(reason, str(exc))

            messages.append(resp.message)
            calls: list[dict[str, Any]] = []
            shown: list[tuple[str, ToolResult]] = []
            for call in resp.tool_calls:
                t0 = time.perf_counter()
                out = self.execute(call.name, call.arguments)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(out.content, default=str)})
                calls.append({"id": call.id, "name": call.name, "arguments": _parsed(call.arguments),
                              "result": out.summary, "content": out.content, "image": out.image_file,
                              "ms": int((time.perf_counter() - t0) * 1000)})
                if out.image is not None:
                    shown.append((call.id, out))
            if shown:  # images cannot ride in tool messages: one user message after all tool results
                parts: list[dict[str, Any]] = []
                for call_id, out in shown:
                    parts.append({"type": "text", "text": f"Image from look (call {call_id}): {out.image_file}"})
                    parts.append(image_part(out.image))
                parts.append({"type": "text", "text": AFTER_IMAGE})
                messages.append({"role": "user", "content": parts})
            if not resp.tool_calls:
                messages.append({"role": "user", "content": NUDGE})

            self._turn_event({
                "n": n, "text": resp.text, "tool_calls": calls,
                "tokens": {"in": resp.tokens_in, "cached": resp.tokens_cached, "out": resp.tokens_out},
                "cost_usd": round(resp.cost_usd, 6), "latency_ms": resp.latency_ms,
                "image": shown[-1][1].image_file if shown else None,
                "model": resp.model, "request_sha256": resp.request_sha256, "finish_reason": resp.finish_reason,
            })
            if self.end is not None:
                return self.end
        return _auto_end("turn limit", f"no finish or handoff after {max_turns} turns")

    def _turn_event(self, fields: dict[str, Any]) -> None:
        turn = {"type": "turn", **fields}
        self.log.write(turn)
        self.emit(turn)

    # -- dispatch ------------------------------------------------------------

    def execute(self, name: str, raw_args: str) -> ToolResult:
        """Run one tool call. Bad input is answered as a tool error so the model can correct itself."""
        if self.end is not None:
            return _error("ignored: the run already ended", "ignored")
        if name not in TOOL_NAMES:
            return _error(f"unknown tool {name!r}; the tools are {', '.join(TOOL_NAMES)}", "unknown tool")
        try:
            args = json.loads(raw_args or "{}")
        except json.JSONDecodeError as exc:
            return _error(f"arguments are not valid JSON ({exc.msg}); send a JSON object", "bad JSON")
        if not isinstance(args, dict):
            return _error("arguments must be a JSON object", "bad arguments")
        try:
            if name in FIX_TOOLS:
                return self.fix(name)
            return getattr(self, f"tool_{name}")(args)
        except BudgetExceeded as exc:  # read_text's model call would pass the cap
            self.end = _auto_end("budget", str(exc))
            return _error("spend cap reached; the run ends here", "budget")

    # -- tools ---------------------------------------------------------------

    def tool_check(self, args: dict[str, Any]) -> ToolResult:
        report = run_checks(self.art, self.spec, self.profile)
        self.emit({"type": "findings", "stage": "check", "report": report.to_dict()})
        return ToolResult({"ok": True, "findings": _findings_for_model(report.findings)}, _summary(report.findings))

    def tool_look(self, args: dict[str, Any]) -> ToolResult:
        view = args.get("view", "proof")
        if view == "proof":
            img = render_proof(self.art, self.spec, self.profile)
        elif view == "overlay":
            img = render_overlay(self.art, run_checks(self.art, self.spec, self.profile))
        else:
            return _error('view must be "proof" or "overlay"', "bad view")
        self.looks += 1
        name, shown = self._save_seen(img, f"look-{self.looks}", view)
        content = {"ok": True, "view": view, "file": name, "note": "The image follows in the next user message."}
        return ToolResult(content, name, image=shown, image_file=name)

    def _save_seen(self, img: Image.Image | Any, key: str, label: str) -> tuple[str, Image.Image]:
        """Save exactly what the model will see (768 px long side) and list it in the outputs."""
        shown = prepare_image(img)
        name = self.outputs[key] = f"{key}-{label}.png"
        shown.save(self.out_dir / name)
        return name, shown

    def tool_read_text(self, args: dict[str, Any]) -> ToolResult:
        self.text_findings = vision.check_text(self.art, self.spec, self.profile, self.client)
        self.emit({"type": "findings", "stage": "read_text", "report": Report(self.text_findings).to_dict()})
        items = self.text_findings[0].measured.get("items", [])
        content = {
            "ok": True,
            "findings": [{k: f.to_dict()[k] for k in ("check", "status", "fixer", "message")} for f in self.text_findings],
            "text": [{k: i.get(k) for k in ("seen", "intended", "garbled", "cap_height_pt")} for i in items],
        }
        return ToolResult(content, _summary(self.text_findings))

    def tool_finish(self, args: dict[str, Any]) -> ToolResult:
        message = args.get("customer_message")
        if not isinstance(message, str) or not message.strip():
            return _error("customer_message must be a non-empty string", "refused: no message")
        words = len(message.split())
        if words > MAX_MESSAGE_WORDS:
            return _error(f"customer_message has {words} words; keep it under {MAX_MESSAGE_WORDS}", "refused: too long")
        if self.art.cut is None:
            return _error("there is no cut line yet: run add_border (or fit_shape for a scene) first, or hand off",
                          "refused: no cut line")
        self.end = End(handoff=False, reason=None, draft_message=message.strip())
        return ToolResult({"ok": True, "note": "Run finished."}, "finished")

    def tool_handoff(self, args: dict[str, Any]) -> ToolResult:
        reason = str(args.get("reason") or "").strip() or "unspecified"
        notes = args.get("person_notes") or []
        notes = [str(n) for n in notes] if isinstance(notes, list) else [str(notes)]
        self.end = End(handoff=True, reason=reason, person_notes=notes)
        return ToolResult({"ok": True, "note": "Handed off to a person."}, f"handoff: {reason}")

    def fix(self, name: str) -> ToolResult:
        """Run one fix through the damage guard (guard.apply_fix records exactly one Step: applied,
        refused, or reverted as damaged). A refused or damaged fix leaves the pixels as they were."""
        try:
            self.art = guard.apply_fix(name, self.art, self.spec, self.profile).art
        except Exception as exc:  # a crashing fix is reported to the model like a refusal
            self.art = self.art.copy()
            self.art.history.append(Step(fix=name, ok=False, damaged=False, note=f"error: {type(exc).__name__}: {exc}"))
        step = self.art.history[-1]
        n = len(self.art.history)
        preview = self.outputs[f"step-{n}"] = f"step-{n}-{name}.png"
        save_png(self.art.rgba, self.out_dir / preview)
        self.emit({"type": "step", "index": n, "step": step.to_dict(), "preview": preview})
        status = "damaged, reverted" if step.damaged else ("ok" if step.ok else "refused")
        content = {k: v for k, v in step.to_dict().items() if k != "guard"}
        return ToolResult(content, f"{name}: {status}")


# ---------------------------------------------------------------- entry point

def run_agent(
    path: str | Path,
    spec: Spec,
    profile: Profile,
    out_dir: str | Path,
    client: ChatClient,
    on_event: EventFn | None = None,
    max_turns: int = MAX_TURNS,
) -> RunResult:
    """Agent mode on one image: the tool loop, the outcome from types.outcome(), outputs via
    pipeline.write_outputs, every call and turn in out_dir/log.jsonl. Use one client per run."""
    t0 = time.perf_counter()
    path, out_dir = Path(path), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    emit = on_event or (lambda event: None)
    log = _Log(out_dir / LOG_NAME)
    try:
        try:
            original = load_artwork(path, spec, profile)
        except ImageLoadError as exc:  # nothing for a model to look at: no call is made
            original, before = None, load_failure_report(str(exc))
            emit({"type": "findings", "stage": "before", "report": before.to_dict()})
            art, final, end, cost, outputs = None, before, End(handoff=False, reason=None), 0.0, {"log": LOG_NAME}
        else:
            before = run_checks(original, spec, profile)
            emit({"type": "findings", "stage": "before", "report": before.to_dict()})
            run = _Run(original, spec, profile, out_dir, client, emit, log)
            end = run.converse(path, before, max_turns)
            art, cost, outputs = run.art, run.cost_usd, run.outputs
            final = Report(run_checks(art, spec, profile).findings + run.text_findings)

        result = outcome(art, final, handoff=end.handoff)
        message, notes = _message_and_notes(result, art, final, end, spec)
        run_result = RunResult(
            mode="agent", art=art, before=before, after=final, outcome=result, customer_message=message,
            person_notes=notes, handoff_reason=end.reason, cost_usd=round(cost, 6), outputs=outputs,
            spec=spec, profile=profile, original=original, elapsed_s=time.perf_counter() - t0,
        )
        log.write({"type": "end", "outcome": result, "handoff": end.handoff, "handoff_reason": end.reason,
                   "cost_usd": run_result.cost_usd, "history": [s.to_dict() for s in (art.history if art else [])]})
        emit({"type": "findings", "stage": "after", "report": final.to_dict()})
        pipeline.write_outputs(run_result, out_dir)
        emit({"type": "done", "result": run_result.to_dict()})
        return run_result
    except Exception as exc:  # a crash is still reported to the workbench before it propagates
        log.write({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        emit({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        raise


def _message_and_notes(result: str, art: Artwork | None, final: Report, end: End, spec: Spec) -> tuple[str, list[str]]:
    """The model's message goes to the customer only when the outcome lets the proof go out.
    Otherwise the shared template says a person will check, and the model's draft is a note."""
    notes = list(end.person_notes)
    if end.draft_message and result != "needs_person":
        return end.draft_message, notes
    if end.draft_message:
        notes.append(f"The agent finished, but the final checks need a person. Its draft message: {end.draft_message}")
    if result == "needs_person":
        notes += [n for n in pipeline.person_notes(art, final) if n not in notes]
    return pipeline.customer_message(result, art, final, spec), notes
