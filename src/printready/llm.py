"""One small OpenAI-compatible client (chat completions + xAI image generation) and a fake provider.

Model strings are "<provider>:<model>":
    xai:grok-4.3          https://api.x.ai/v1, key XAI_API_KEY (what every project run uses)
    openrouter:<model>    https://openrouter.ai/api/v1, OPENROUTER_API_KEY (portability only)
    openai:<model>        https://api.openai.com/v1, OPENAI_API_KEY (portability only)
    fake:<script.json>    replays scripted responses; offline tests run through the same code path

Every call: spend estimate and cap check BEFORE the request (spend.py), temperature 0, timeouts,
three retries with backoff on 429/5xx only, usage parsed (cached and reasoning tokens included),
actual cost recorded to the ledger, and a call record handed to every listener before the result
is returned. A refusal, an error or a budget stop is logged as an outcome, never dropped.
Keys come from the environment (optionally a dotenv file) and are never printed or logged.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

import httpx
import numpy as np
from PIL import Image

from printready import spend
from printready.spend import BudgetExceeded, Price

DEFAULT_MODEL = "xai:grok-4.3"

# provider -> (base URL, environment variable that holds the key)
PROVIDERS: dict[str, tuple[str, str]] = {
    "xai": ("https://api.x.ai/v1", "XAI_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
}

MAX_IMAGE_SIDE = 768  # images sent to a model are downscaled to this long side, never upscaled
MAX_TOKENS = 4096  # completion budget per call; also the worst case the spend estimate assumes
RETRIES = 3  # extra attempts after the first, on 429 and 5xx only
BACKOFF_S = (1.0, 2.0, 4.0)
MAX_RETRY_AFTER_S = 30.0
TIMEOUT_S = 120.0  # read timeout; reasoning models can think for a while
CONNECT_TIMEOUT_S = 10.0
CHARS_PER_TOKEN = 3.5  # pre-call estimate only (conservative)
IMAGE_TOKENS_ESTIMATE = 2000  # pre-call estimate per input image at 768 px (conservative)
USD_TICKS = 1e10  # xAI usage.cost_in_usd_ticks per US dollar

CallListener = Callable[[dict[str, Any]], None]
_KEY_PATTERN = re.compile(r"\b(?:xai|sk|sk-or)-[A-Za-z0-9_\-]{6,}")


class LLMError(RuntimeError):
    """A model call failed: HTTP error after retries, a timeout, or an unusable response."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON text exactly as the model sent it (it may be invalid)


@dataclass
class ChatResponse:
    text: str  # "" when the model only called tools
    tool_calls: list[ToolCall]
    message: dict[str, Any]  # the assistant message, ready to append to the conversation
    model: str  # model id the API returned
    finish_reason: str | None
    refusal: str | None
    tokens_in: int  # all prompt tokens, cached included
    tokens_cached: int
    tokens_out: int  # completion + reasoning
    usage: dict[str, Any]  # the raw usage block, as returned
    cost_usd: float = 0.0  # from the price table and the usage above
    latency_ms: int = 0
    request_sha256: str = ""


@dataclass
class ImageResult:
    data: bytes  # the encoded image as returned (JPEG or PNG)
    revised_prompt: str | None  # the prompt the image model actually used, if it says
    model: str  # model id the API returned
    cost_usd: float
    request_sha256: str


# ---------------------------------------------------------------- transports

class HttpTransport:
    """POSTs JSON bytes to an OpenAI-compatible base URL. Holds the key; never exposes it."""

    def __init__(self, base_url: str, api_key: str, timeout_s: float = TIMEOUT_S) -> None:
        self.secrets = (api_key,)
        self._http = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=httpx.Timeout(timeout_s, connect=CONNECT_TIMEOUT_S),
        )

    def post(self, path: str, payload: bytes) -> tuple[int, Any, dict[str, str]]:
        r = self._http.post(path.lstrip("/"), content=payload)
        try:
            data = r.json()
        except ValueError:
            data = r.text
        return r.status_code, data, dict(r.headers)

    def close(self) -> None:
        self._http.close()


class FakeTransport:
    """Replays scripted responses, one per request, and keeps every request body for assertions.

    Script entries (shorthand is expanded to the OpenAI wire format, so parsing is exercised):
      {"text": "...", "tool_calls": [{"name": "check", "arguments": {} | "raw text"}],
       "usage": {"in": 1200, "cached": 0, "out": 80}, "model": "fake-1"}
      {"status": 503}                       an HTTP error (retried if 429/5xx)
      {"timeout": true}                     a transport timeout
      {"b64_json": "<base64 png>"}          an image generation result
      {"choices": [...], ...}               a raw response, passed through
    """

    secrets: tuple[str, ...] = ()

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    def post(self, path: str, payload: bytes) -> tuple[int, Any, dict[str, str]]:
        self.requests.append({"path": path, "body": json.loads(payload)})
        if not self.responses:
            raise LLMError(f"fake script has no response left for request {len(self.requests)}")
        entry = self.responses.pop(0)
        if entry.get("timeout"):
            raise httpx.ReadTimeout("fake timeout")
        if "status" in entry and entry["status"] != 200:
            return int(entry["status"]), {"error": {"message": entry.get("body", "fake error")}}, {}
        if "choices" in entry or "data" in entry:
            return 200, entry, {}
        if "b64_json" in entry:
            return 200, {"data": [{"b64_json": entry["b64_json"], "revised_prompt": entry.get("revised_prompt")}]}, {}
        return 200, _expand_fake_chat(entry, len(self.requests)), {}

    def close(self) -> None:
        pass


def _expand_fake_chat(entry: dict[str, Any], n: int) -> dict[str, Any]:
    calls = []
    for i, tc in enumerate(entry.get("tool_calls", [])):
        args = tc.get("arguments", {})
        calls.append({
            "id": tc.get("id", f"call_{n}_{i}"),
            "type": "function",
            "function": {"name": tc["name"], "arguments": args if isinstance(args, str) else json.dumps(args)},
        })
    message: dict[str, Any] = {"role": "assistant", "content": entry.get("text")}
    if calls:
        message["tool_calls"] = calls
    if entry.get("refusal"):
        message["refusal"] = entry["refusal"]
    usage = entry.get("usage", {})
    tin, cached, tout = usage.get("in", 100), usage.get("cached", 0), usage.get("out", 20)
    return {
        "model": entry.get("model", "fake"),
        "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if calls else "stop"}],
        "usage": {
            "prompt_tokens": tin,
            "completion_tokens": tout,
            "total_tokens": tin + tout,
            "prompt_tokens_details": {"cached_tokens": cached},
        },
    }


# ---------------------------------------------------------------- client

class ChatClient:
    """One model behind one transport. `chat()` for chat completions, `image()` for xAI images."""

    def __init__(
        self,
        model: str,
        transport: HttpTransport | FakeTransport,
        *,
        price: Price,
        ledger: str | Path | None = None,
        on_call: CallListener | None = None,
        max_tokens: int = MAX_TOKENS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = model  # "<provider>:<name>", as given to make_client
        self.provider, _, self.name = model.partition(":")
        self.transport = transport
        self.price = price
        self.ledger = ledger  # None: spend.ledger_path() at call time
        self.max_tokens = max_tokens
        self.sleep = sleep
        self.listeners: list[CallListener] = [on_call] if on_call else []
        self.calls: list[dict[str, Any]] = []  # every call record this client produced

    @property
    def cost_usd(self) -> float:
        """Total cost of every call this client made (rules mode reads it to cost the vision check)."""
        return sum(c.get("cost_usd", 0.0) for c in self.calls)

    @contextmanager
    def listening(self, listener: CallListener) -> Iterator[None]:
        """Also hand every call record to `listener` inside this block (e.g. a run's log.jsonl)."""
        self.listeners.append(listener)
        try:
            yield
        finally:
            self.listeners.remove(listener)

    def close(self) -> None:
        self.transport.close()

    # -- chat ----------------------------------------------------------------

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        purpose: str = "chat",
        max_tokens: int | None = None,
    ) -> ChatResponse:
        """One chat-completions call at temperature 0. Raises BudgetExceeded (before the call)
        or LLMError; both are logged first."""
        limit = max_tokens or self.max_tokens
        body: dict[str, Any] = {"model": self.name, "messages": messages, "temperature": 0, "max_tokens": limit}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        est = spend.estimate(self.price, tokens_in=estimate_prompt_tokens(messages, tools), tokens_out=limit)
        data, rec = self._request("/chat/completions", body, purpose, est)
        try:
            resp = _parse_chat(data)
        except LLMError as exc:
            self._log({**rec, "status": "error", "error": str(exc)})
            raise
        resp.cost_usd = spend.cost(self.price, resp.tokens_in, resp.tokens_cached, resp.tokens_out)
        resp.latency_ms, resp.request_sha256 = rec["latency_ms"], rec["request_sha256"]
        self._record_spend(resp.tokens_in, resp.tokens_cached, resp.tokens_out, 0, resp.cost_usd, purpose)
        rec.update(
            status="refusal" if resp.refusal else "ok",
            model_returned=resp.model,
            finish_reason=resp.finish_reason,
            tokens_in=resp.tokens_in,
            tokens_cached=resp.tokens_cached,
            tokens_out=resp.tokens_out,
            cost_usd=round(resp.cost_usd, 6),
            usage=resp.usage,
        )
        if "cost_in_usd_ticks" in resp.usage:  # xAI's own figure (1 tick = 1e-10 USD), kept as a cross-check
            rec["cost_reported_usd"] = round(resp.usage["cost_in_usd_ticks"] / USD_TICKS, 6)
        self._log(rec)
        return resp

    # -- images --------------------------------------------------------------

    def image(self, prompt: str, *, purpose: str = "image", **opts: Any) -> bytes:
        """One generated image (n=1, b64_json, aspect_ratio 1:1 unless given) as encoded bytes."""
        return self.image_result(prompt, purpose=purpose, **opts).data

    def image_result(self, prompt: str, *, purpose: str = "image", **opts: Any) -> ImageResult:
        """Like image(), with the revised prompt (if the API returns one), model id and cost."""
        body = {"model": self.name, "prompt": prompt, "n": 1, "response_format": "b64_json", "aspect_ratio": "1:1"}
        body.update(opts)
        est = spend.estimate(self.price, images=1)
        data, rec = self._request("/images/generations", body, purpose, est)
        try:
            item = data["data"][0]
            raw = base64.b64decode(item["b64_json"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            self._log({**rec, "status": "error", "error": f"image response has no b64_json ({exc})"})
            raise LLMError(f"image response has no b64_json ({exc})") from None
        usd = spend.cost(self.price, images=1)
        self._record_spend(0, 0, 0, 1, usd, purpose)
        model = str(data.get("model") or self.name)
        rec.update(status="ok", model_returned=model, images=1, cost_usd=round(usd, 6))
        self._log(rec)
        return ImageResult(data=raw, revised_prompt=item.get("revised_prompt") or None, model=model, cost_usd=usd,
                           request_sha256=rec["request_sha256"])

    # -- shared plumbing -----------------------------------------------------

    def _request(self, path: str, body: dict[str, Any], purpose: str, est: float) -> tuple[Any, dict[str, Any]]:
        """Cap check, POST with retries, latency. Returns (response JSON, partial call record)."""
        payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        rec: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "purpose": purpose,
            "provider": self.provider,
            "model": self.name,
            "request_sha256": hashlib.sha256(payload).hexdigest(),
            "estimate_usd": round(est, 6),
            "cost_usd": 0.0,
        }
        try:
            spend.check_cap(est, self.ledger)
        except BudgetExceeded as exc:
            self._log({**rec, "status": "budget", "error": str(exc), "latency_ms": 0, "attempts": 0})
            raise
        t0 = time.perf_counter()
        attempts = 0
        try:
            for attempt in range(RETRIES + 1):
                attempts = attempt + 1
                try:
                    status, data, headers = self.transport.post(path, payload)
                except httpx.HTTPError as exc:
                    # Not retried: a timed-out request may still have run (and been billed).
                    raise LLMError(f"{type(exc).__name__}: {self._scrub(str(exc))}") from None
                if status == 200:
                    rec.update(latency_ms=_ms_since(t0), attempts=attempts)
                    return data, rec
                if (status == 429 or status >= 500) and attempt < RETRIES:
                    self.sleep(_backoff_s(attempt, headers))
                    continue
                raise LLMError(f"HTTP {status}: {self._scrub(_error_text(data))}")
        except LLMError as exc:
            self._log({**rec, "status": "error", "error": str(exc), "latency_ms": _ms_since(t0), "attempts": attempts})
            raise
        raise AssertionError("unreachable")  # pragma: no cover

    def _record_spend(self, tin: int, cached: int, tout: int, images: int, usd: float, purpose: str) -> None:
        if not self.price.free:  # scripted fake calls never touch the real ledger
            spend.record(self.provider, self.name, tin, cached, tout, images, usd, purpose, path=self.ledger)

    def _log(self, rec: dict[str, Any]) -> None:
        self.calls.append(rec)
        for listener in list(self.listeners):
            listener(rec)

    def _scrub(self, text: str) -> str:
        for secret in getattr(self.transport, "secrets", ()):
            if secret:
                text = text.replace(secret, "[redacted]")
        return _KEY_PATTERN.sub("[redacted]", text)[:500]


def _parse_chat(data: Any) -> ChatResponse:
    """The first choice of a chat-completions response; cost, latency and hash are filled in later."""
    try:
        choice = data["choices"][0]
        msg = choice["message"]
    except (KeyError, IndexError, TypeError):
        raise LLMError(f"response has no choices: {str(data)[:200]}") from None
    content = msg.get("content")
    if isinstance(content, list):  # some providers return content parts
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    calls = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        args = fn.get("arguments")
        calls.append(ToolCall(
            id=str(tc.get("id") or f"call_{len(calls)}"),
            name=str(fn.get("name", "")),
            arguments=args if isinstance(args, str) else json.dumps(args if args is not None else {}),
        ))
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}} for c in calls
        ]
    usage = data.get("usage") or {}
    tin = int(usage.get("prompt_tokens") or 0)
    cached = int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    total = usage.get("total_tokens")
    # xAI reports reasoning tokens outside completion_tokens (total = prompt + completion +
    # reasoning); OpenAI counts them inside. Either way everything past the prompt bills as output.
    tout = max(completion, int(total) - tin) if total else completion
    return ChatResponse(
        text=content or "", tool_calls=calls, message=message, model=str(data.get("model", "")),
        finish_reason=choice.get("finish_reason"), refusal=msg.get("refusal") or None,
        tokens_in=tin, tokens_cached=cached, tokens_out=tout, usage=usage,
    )


def _error_text(data: Any) -> str:
    if isinstance(data, dict):
        err = data.get("error", data)
        if isinstance(err, dict):
            return str(err.get("message") or err)
        return str(err)
    return str(data)


def _backoff_s(attempt: int, headers: dict[str, str]) -> float:
    retry_after = {k.lower(): v for k, v in headers.items()}.get("retry-after")
    try:
        return min(float(retry_after), MAX_RETRY_AFTER_S)
    except (TypeError, ValueError):
        return BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)]


def _ms_since(t0: float) -> int:
    return int(round((time.perf_counter() - t0) * 1000))


def estimate_prompt_tokens(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> int:
    """A generous token count for the spend estimate: text chars / 3.5, plus a flat cost per image."""
    chars, images = 0, 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            for part in content:
                if part.get("type") == "image_url":
                    images += 1
                else:
                    chars += len(str(part.get("text", "")))
        elif content:
            chars += len(str(content))
        if m.get("tool_calls"):
            chars += len(json.dumps(m["tool_calls"]))
        chars += 16  # role and framing
    if tools:
        chars += len(json.dumps(tools))
    return int(chars / CHARS_PER_TOKEN) + images * IMAGE_TOKENS_ESTIMATE


# ---------------------------------------------------------------- images in messages

def prepare_image(image: Image.Image | np.ndarray, max_side: int = MAX_IMAGE_SIDE) -> Image.Image:
    """RGB copy, downscaled so the long side is at most `max_side` (never upscaled).
    RGBA is flattened onto white. Save the result to keep a record of exactly what a model saw."""
    img = Image.fromarray(image) if isinstance(image, np.ndarray) else image
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.getchannel("A"))
        img = flat
    else:
        img = img.convert("RGB")
    scale = max_side / max(img.size)
    if scale < 1:
        img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
    return img


def image_part(image: Image.Image | np.ndarray, max_side: int = MAX_IMAGE_SIDE) -> dict[str, Any]:
    """An OpenAI-style image content part: the image as a PNG data URL, at most `max_side` px."""
    buf = io.BytesIO()
    prepare_image(image, max_side).save(buf, format="PNG")
    url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": url, "detail": "high"}}


# ---------------------------------------------------------------- construction

def load_env_file(path: str | Path, override: bool = False) -> list[str]:
    """Load KEY=VALUE lines from a dotenv file into os.environ (existing values win unless
    `override`). Returns the variable NAMES set, never values. Empty values are skipped."""
    names = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] in "'\"" and value[-1] == value[0]:
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        if not key.isidentifier() or not value:
            continue
        if override or key not in os.environ:
            os.environ[key] = value
            names.append(key)
    return names


def default_env_file() -> Path:
    """The repo-root .env (gitignored)."""
    return spend.repo_root() / ".env"


def load_fake_script(path: str | Path) -> tuple[list[dict[str, Any]], Price]:
    """A fake script: a JSON list of responses, or {"price": {...Price fields}, "responses": [...]}."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data, Price()
    return list(data["responses"]), Price(**data.get("price", {}))


def make_client(
    model: str,
    env_file: str | Path | None = None,
    *,
    price: Price | None = None,
    ledger: str | Path | None = None,
    on_call: CallListener | None = None,
    timeout_s: float = TIMEOUT_S,
    sleep: Callable[[float], None] = time.sleep,
) -> ChatClient:
    """Build a client for "<provider>:<model>". Real providers load `env_file` (default: the
    repo-root .env if present) and read the key from the environment. Unknown prices are refused
    here, before any call, unless `price` is given."""
    provider, _, name = model.partition(":")
    if not name:
        raise ValueError(f"model must look like '<provider>:<model>', got {model!r}")
    if provider == "fake":
        responses, script_price = load_fake_script(name)
        return ChatClient(model, FakeTransport(responses), price=price or script_price, ledger=ledger,
                          on_call=on_call, sleep=sleep)
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}; use one of {', '.join(PROVIDERS)} or fake")
    resolved_price = spend.price_for(model, price)
    env_path = Path(env_file) if env_file is not None else default_env_file()
    if env_file is not None or env_path.exists():
        load_env_file(env_path)
    base_url, key_var = PROVIDERS[provider]
    key = os.environ.get(key_var, "").strip()
    if not key:
        raise LLMError(f"{key_var} is not set; put it in the repo .env or pass --env-file")
    return ChatClient(model, HttpTransport(base_url, key, timeout_s), price=resolved_price, ledger=ledger,
                      on_call=on_call, sleep=sleep)


def generate_image(model: str, prompt: str, **opts: Any) -> bytes:
    """One image from xAI POST /v1/images/generations (b64_json, n=1, aspect_ratio 1:1 by
    default), through the spend guard. `opts` may hold env_file, ledger, on_call, price, and
    request fields such as aspect_ratio or resolution."""
    client_opts = {k: opts.pop(k) for k in ("env_file", "ledger", "on_call", "price", "sleep") if k in opts}
    provider = model.partition(":")[0]
    if provider not in ("xai", "fake"):
        raise ValueError(f"image generation is xAI only, got {model!r}")
    client = make_client(model, **client_opts)
    try:
        return client.image(prompt, **opts)
    finally:
        client.close()
