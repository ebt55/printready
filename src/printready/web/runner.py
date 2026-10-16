"""The ONE adapter between the workbench and the real pipeline (K3 rules mode, K4 agent mode).

Everything here imports lazily, so the server starts (and `--demo` works) before those land, and
the live path starts working the moment they do. The contract it relies on (01-DESIGN.md,
04-WORKBENCH.md "Integration contract"):

    pipeline.run_rules(path, spec, profile, out_dir, client=None, on_event=None) -> RunResult
    agent.run_agent(path, spec, profile, out_dir, client, on_event=None) -> RunResult
    on_event({"type": "step" | "turn" | "findings" | "done" | "error", ...})

The return value may be a RunResult (anything with to_dict()) or a plain dict of the same shape.
If the runner does not emit `done` itself, the job emits it with the returned result.
"""

from __future__ import annotations

import inspect
import traceback
from pathlib import Path
from typing import Any, Callable

from printready.web.runs import RunJob, jsonable

RULES_PARAMS = {"out_dir", "on_event"}
AGENT_PARAMS = {"out_dir", "client", "on_event"}


def _check(module: str, func: str, needed: set[str]) -> dict:
    try:
        mod = __import__(f"printready.{module}", fromlist=[func])
        fn = getattr(mod, func)
        params = set(inspect.signature(fn).parameters)
    except Exception as exc:  # import error, missing function, ...
        return {"ready": False, "reason": f"printready.{module}.{func} is not available ({exc.__class__.__name__})"}
    missing = needed - params
    if missing:
        return {"ready": False, "reason": f"printready.{module}.{func} does not take {', '.join(sorted(missing))} yet"}
    return {"ready": True, "reason": ""}


def live_status() -> dict:
    """Whether the real rules and agent runners are wired, judged by their signatures."""
    return {"rules": _check("pipeline", "run_rules", RULES_PARAMS),
            "agent": _check("agent", "run_agent", AGENT_PARAMS)}


def _spec_and_profile(size_in: float):
    from printready.profile import load_profile
    from printready.types import Spec

    return Spec(product="die_cut", size_in=float(size_in)), load_profile()


def make_client(model: str, out_dir: Path):
    """A live LLM client for `model` from printready.llm (K4); it records spend to the real ledger."""
    from printready import llm

    return llm.make_client(model)


def call_run_rules(path: Path, size_in: float, out_dir: Path, on_event: Callable[[dict], None],
                   vision_model: str | None = None, client: Any = None) -> dict:
    """run_rules with a vision client for `vision_model` (or the given `client`), as a JSON dict."""
    from printready.pipeline import run_rules

    spec, profile = _spec_and_profile(size_in)
    if client is None and vision_model:
        client = make_client(vision_model, out_dir)
    result = run_rules(Path(path), spec, profile, Path(out_dir), client=client, on_event=on_event)
    return jsonable(result)


def call_run_agent(path: Path, size_in: float, out_dir: Path, on_event: Callable[[dict], None], model: str,
                   client: Any = None) -> dict:
    """run_agent with a client for `model` (or the given `client`, e.g. the demo's scripted one)."""
    from printready.agent import run_agent

    spec, profile = _spec_and_profile(size_in)
    if client is None:
        client = make_client(model, out_dir)
    result = run_agent(Path(path), spec, profile, Path(out_dir), client, on_event=on_event)
    return jsonable(result)


class LiveRunner:
    """Runs the real pipeline. Errors become an `error` event with a readable message."""

    engine = "live"

    def run(self, job: RunJob) -> None:
        job.mark_running()
        try:
            if job.mode == "agent":
                result = call_run_agent(job.input_path, job.size_in, job.dir, job.emit, job.model or "xai:grok-4.3")
            else:
                result = call_run_rules(job.input_path, job.size_in, job.dir, job.emit,
                                        vision_model=job.model if job.vision else None)
            job.finish(result)
        except NotImplementedError as exc:
            job.fail(f"{job.mode} mode is not implemented yet ({exc or 'pending chunk'}). "
                     "Start with --demo to explore with simulated runs.")
        except Exception as exc:  # surfaced to the UI; full trace on the server console
            traceback.print_exc()
            name = exc.__class__.__name__
            job.fail(f"{name}: {exc}" if str(exc) else name)


class DemoRunner:
    """`--demo`: replays a saved run when one matches the request exactly; otherwise runs the real
    pipeline live with the scripted demo model (demo_script.py). Nothing is ever charged."""

    engine = "demo"

    def __init__(self, speed: float = 1.0, demo_dir: Path | None = None, samples_dir: Path | None = None):
        self.speed = speed
        self.demo_dir = demo_dir
        self.samples_dir = samples_dir

    def run(self, job: RunJob) -> None:
        from printready.web import demo

        job.mark_running()
        try:
            sample = None
            canned = None
            if job.sample_id:
                sample = next((s for s in demo.load_samples(self.samples_dir) if s["id"] == job.sample_id), None)
                canned = demo.canned_run_dir(job.sample_id, job.mode, job.size_in, job.vision, self.demo_dir)
            if canned is not None:
                demo.replay(canned, job.dir, job.emit, self.speed)
            else:
                vision = (sample or {}).get("vision") if sample else None
                emit = demo.spaced(job.emit, self.speed) if job.mode == "rules" else job.emit
                result = demo.run_demo_image(job.input_path, job.dir, job.mode, emit, size_in=job.size_in,
                                             vision=vision, use_vision=job.vision,
                                             agent_opts=(sample or {}).get("agent"), speed=self.speed)
                job.finish(result)
            job.finish(None)  # no-op once `done` was emitted
        except NotImplementedError as exc:
            job.fail(f"{job.mode} mode is not implemented yet ({exc or 'pending chunk'}).")
        except Exception as exc:
            traceback.print_exc()
            job.fail(f"{exc.__class__.__name__}: {exc}")


def to_result_dict(result: Any) -> dict:
    return jsonable(result)
