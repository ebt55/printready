"""Mechanical preregistration: freeze the artifacts PREREG.md names, and verify them later.

`freeze` hashes every frozen artifact (03-EVAL section 3 item 1) and writes a fenced JSON block
between two markers inside PREREG.md; the prose around it is written by hand. `verify` recomputes
everything and reports a precise diff. `require_verified` is the gate that test-split commands call:
PREREG.md must be committed, unmodified since its last commit, and every frozen value must match.

Hashes are sha256 of the file bytes with CRLF normalised to LF, so a Windows checkout with
autocrlf verifies the same as a Unix one. Settings (model ids, turn limit, temperature) are read
from the code at freeze and verify time, never typed in here.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

PREREG_FILE = "PREREG.md"
START = "<!-- prereg:frozen:start -->"
END = "<!-- prereg:frozen:end -->"
SCHEMA = 1
HASHING = "sha256 of the file bytes with CRLF normalised to LF"
SOURCE_GROUP = "src/printready/**/*.py (excluding web/)"
# The bench generator: everything that decides benchmark images and labels (not the runner/report).
GENERATOR_EXCLUDE = ("run.py", "report.py")


class PreregError(RuntimeError):
    """PREREG.md is missing, not committed, modified, or no longer matches the code and data."""


def default_root() -> Path:
    """The source checkout this module runs from (has pyproject.toml), else the working directory."""
    root = Path(__file__).resolve().parents[2]
    return root if (root / "pyproject.toml").exists() else Path.cwd()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def frozen_files(root: Path) -> dict[str, str]:
    """The named artifacts: label -> repo-relative path (existing or not)."""
    from printready.profile import DEFAULT_PROFILE_NAME

    files = {
        "profile": f"profiles/{DEFAULT_PROFILE_NAME}.yaml",
        "bench manifest (dev)": "data/bench/manifest-dev.jsonl",
        "realset prompts (test)": "realset/prompts.txt",
    }
    for p in sorted((root / "src" / "printready" / "bench").glob("*.py")):
        if p.name not in GENERATOR_EXCLUDE:
            files[f"bench generator: {p.name}"] = _rel(root, p)
    for p in sorted((root / "src" / "printready" / "prompts").glob("*.md")):
        files[f"prompt: {p.name}"] = _rel(root, p)
    return files


def source_files(root: Path) -> list[Path]:
    base = root / "src" / "printready"
    return sorted(p for p in base.rglob("*.py") if "web" not in p.relative_to(base).parts[:1])


def source_group(root: Path) -> dict[str, Any]:
    """Per-file hashes of the package source (web/ excluded) and one combined hash over them."""
    per_file = {_rel(root, p): file_sha256(p) for p in source_files(root)}
    combined = hashlib.sha256("".join(f"{k}\0{v}\n" for k, v in per_file.items()).encode()).hexdigest()
    return {"sha256": combined, "count": len(per_file), "files": per_file}


def observed_temperature() -> float:
    """The temperature the chat client actually sends: one scripted call through the real request
    builder (free fake transport, throwaway ledger)."""
    from printready.llm import ChatClient, FakeTransport
    from printready.spend import Price

    transport = FakeTransport([{"text": "ok", "usage": {"in": 1, "out": 1}}])
    with tempfile.TemporaryDirectory() as tmp:
        client = ChatClient("prereg-probe", transport, price=Price(), ledger=Path(tmp) / "ledger.jsonl")
        client.chat([{"role": "user", "content": "probe"}], purpose="prereg")
        client.close()
    return transport.requests[0]["body"]["temperature"]


def settings() -> dict[str, Any]:
    """Model ids, turn limit, temperature, the text_small switch and the agent's tools, read from
    the code (the tool names come from the tool schema the agent sends to the model)."""
    from printready import agent, llm, vision
    from printready.bench.run import DEFAULT_VISION_MODEL
    from printready.realset import IMAGE_MODELS

    return {
        "vision_and_agent_model": llm.DEFAULT_MODEL,
        "bench_vision_model": DEFAULT_VISION_MODEL,
        "image_models": list(IMAGE_MODELS),
        "agent_max_turns": agent.MAX_TURNS,
        "temperature": observed_temperature(),
        "text_small_default": vision.TEXT_SMALL_DEFAULT,
        "text_small_env": vision.TEXT_SMALL_ENV,
        "agent_tools": [t["function"]["name"] for t in agent.TOOLS],
        "fix_tools": list(agent.FIX_TOOLS),
    }


def snapshot(root: Path | str | None = None) -> dict[str, Any]:
    """Everything the freeze records, computed now."""
    root = Path(root) if root is not None else default_root()
    files = {}
    for label, rel in frozen_files(root).items():
        path = root / rel
        files[label] = {"path": rel, "sha256": file_sha256(path) if path.exists() else None}
    return {"schema": SCHEMA, "hashing": HASHING, "files": files,
            "source": {SOURCE_GROUP: source_group(root)}, "settings": settings()}


# --- PREREG.md block ------------------------------------------------------------------------------


def render_block(snap: dict[str, Any]) -> str:
    lines = [START, "## Frozen artifacts", "",
             "Written by `printready prereg freeze`, checked by `printready prereg verify`. Do not edit by hand.",
             "", "```json", json.dumps(snap, indent=1, ensure_ascii=False), "```", END]
    return "\n".join(lines)


def read_block(text: str) -> dict[str, Any] | None:
    m = re.search(re.escape(START) + r".*?```json\n(.*?)\n```.*?" + re.escape(END), text, re.S)
    return json.loads(m.group(1)) if m else None


def freeze(root: Path | str | None = None) -> tuple[Path, dict[str, Any]]:
    """Write or update the frozen block in PREREG.md (creating the file if needed)."""
    root = Path(root) if root is not None else default_root()
    snap = snapshot(root)
    missing = [v["path"] for v in snap["files"].values() if v["sha256"] is None]
    if missing:
        raise PreregError(f"cannot freeze: missing {', '.join(missing)}")
    path = root / PREREG_FILE
    block = render_block(snap)
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if START in text and END in text:
            head, rest = text.split(START, 1)
            text = head + block + rest.split(END, 1)[1]
        else:
            text = text.rstrip("\n") + "\n\n" + block + "\n"
    else:
        text = ("# Preregistration\n\nTODO: the preregistration text (03-EVAL section 3) goes here, "
                "around the frozen block.\n\n" + block + "\n")
    path.write_text(text, encoding="utf-8", newline="\n")
    return path, snap


def diff(frozen: dict[str, Any], now: dict[str, Any]) -> list[str]:
    """Every difference between a frozen snapshot and the current one, one line each."""
    out = []
    old_files, new_files = frozen.get("files", {}), now["files"]
    for label in sorted(set(old_files) | set(new_files)):
        old, new = old_files.get(label), new_files.get(label)
        if old is None:
            out.append(f"NEW      {new['path']} ({label}) is not in the freeze")
        elif new is None:
            out.append(f"GONE     {old['path']} ({label}) was frozen but is no longer an artifact")
        elif new["sha256"] is None:
            out.append(f"MISSING  {old['path']} ({label})")
        elif old["sha256"] != new["sha256"]:
            out.append(f"CHANGED  {old['path']} ({label}): {old['sha256'][:12]} -> {new['sha256'][:12]}")
    old_src = frozen.get("source", {}).get(SOURCE_GROUP, {})
    new_src = now["source"][SOURCE_GROUP]
    if old_src.get("sha256") != new_src["sha256"]:
        of, nf = old_src.get("files", {}), new_src["files"]
        for rel in sorted(set(of) | set(nf)):
            if rel not in of:
                out.append(f"NEW      {rel} (source)")
            elif rel not in nf:
                out.append(f"MISSING  {rel} (source)")
            elif of[rel] != nf[rel]:
                out.append(f"CHANGED  {rel} (source): {of[rel][:12]} -> {nf[rel][:12]}")
        if not out or not any("(source)" in line for line in out):
            out.append(f"CHANGED  {SOURCE_GROUP}: combined hash differs")
    old_set, new_set = frozen.get("settings", {}), now["settings"]
    for key in sorted(set(old_set) | set(new_set)):
        if old_set.get(key) != new_set.get(key):
            out.append(f"SETTING  {key}: {old_set.get(key)!r} -> {new_set.get(key)!r}")
    return out


def verify(root: Path | str | None = None) -> list[str]:
    """[] when PREREG.md's frozen block matches the code and data now; else the differences."""
    root = Path(root) if root is not None else default_root()
    path = root / PREREG_FILE
    if not path.exists():
        return [f"{PREREG_FILE} does not exist (run `printready prereg freeze`)"]
    frozen = read_block(path.read_text(encoding="utf-8"))
    if frozen is None:
        return [f"{PREREG_FILE} has no frozen block (run `printready prereg freeze`)"]
    return diff(frozen, snapshot(root))


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=60)


def committed_problems(root: Path) -> list[str]:
    """Read-only git: PREREG.md has a commit and no uncommitted changes."""
    try:
        log = _git(root, "log", "--oneline", "--", PREREG_FILE)
        if log.returncode != 0 or not log.stdout.strip():
            return [f"{PREREG_FILE} is not committed"]
        dirty = _git(root, "diff", "--quiet", "HEAD", "--", PREREG_FILE)
    except (OSError, subprocess.SubprocessError) as exc:
        return [f"could not run git: {exc}"]
    return [f"{PREREG_FILE} has uncommitted changes"] if dirty.returncode != 0 else []


def require_verified(root: Path | str | None = None) -> None:
    """Gate for anything that touches the test split: raise PreregError unless PREREG.md exists, is
    committed and unmodified, and its frozen block matches the code and data exactly."""
    root = Path(root) if root is not None else default_root()
    problems = verify(root)
    if not problems:
        problems = committed_problems(root)
    if problems:
        raise PreregError("preregistration check failed:\n  " + "\n  ".join(problems))
