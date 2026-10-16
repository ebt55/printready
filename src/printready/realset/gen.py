"""`realset gen`: one square image per prompt per image model, stored by content hash.

Resumable: a (prompt, model) pair already in the manifest with its file on disk is skipped. Every
call goes through the spend guard; BudgetExceeded stops the batch. An API error on one prompt is
printed and left for a later run (nothing is written for it).
"""

from __future__ import annotations

import hashlib
import io
import time
from typing import Any, Callable

from PIL import Image

from printready.llm import ChatClient, LLMError, make_client
from printready.realset import ID_PREFIX, Paths, append_jsonl, load_prompts, read_jsonl

EXTENSIONS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}


def generate(
    paths: Paths,
    models: list[str],
    client_factory: Callable[[str], ChatClient] = make_client,
    log: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    """Generate the missing images for `paths.split`; returns the new manifest entries."""
    prompts = load_prompts(paths.prompts, ID_PREFIX[paths.split])
    done = {(e["prompt_id"], e["model"]) for e in read_jsonl(paths.manifest) if (paths.data / e["file"]).exists()}
    (paths.data / "images").mkdir(parents=True, exist_ok=True)
    new: list[dict[str, Any]] = []
    for model in models:
        todo = [(pid, p) for pid, p in prompts if (pid, model) not in done]
        if not todo:
            continue
        client = client_factory(model)
        try:
            for pid, prompt in todo:
                try:
                    result = client.image_result(prompt, purpose=f"realset-{paths.split}")
                except LLMError as exc:
                    log(f"  {pid} {model}: failed ({exc}); run again to retry")
                    continue
                entry = _store(paths, pid, prompt, model, result)
                append_jsonl(paths.manifest, [entry])  # written per image, so a crash loses nothing
                new.append(entry)
                log(f"  {pid} {model}: {entry['width']}x{entry['height']} {entry['format']} "
                    f"{entry['sha256'][:12]} ${entry['cost_usd']:.2f}")
        finally:
            client.close()
    return new


def _store(paths: Paths, pid: str, prompt: str, model: str, result: Any) -> dict[str, Any]:
    sha = hashlib.sha256(result.data).hexdigest()
    with Image.open(io.BytesIO(result.data)) as im:
        fmt, (w, h) = im.format or "PNG", im.size
    rel = f"images/{sha}.{EXTENSIONS.get(fmt, 'png')}"
    (paths.data / rel).write_bytes(result.data)
    return {
        "prompt_id": pid,
        "prompt": prompt,
        "model": model,
        "model_returned": result.model,
        "sha256": sha,
        "file": rel,
        "bytes": len(result.data),
        "width": w,
        "height": h,
        "format": fmt,
        "revised_prompt": result.revised_prompt,
        "cost_usd": round(result.cost_usd, 4),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
