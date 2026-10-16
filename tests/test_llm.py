import base64
import hashlib
import io
import json
import os

import numpy as np
import pytest
from PIL import Image

from printready import llm, spend
from printready.llm import ChatClient, FakeTransport, LLMError
from printready.spend import BudgetExceeded, Price, UnknownPrice


@pytest.fixture(autouse=True)
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "ledger.jsonl"
    monkeypatch.setenv(spend.LEDGER_ENV, str(path))
    monkeypatch.delenv(spend.CAP_ENV, raising=False)
    return path


def fake(tmp_path, responses, price=None, **kw):
    script = tmp_path / "script.json"
    data = {"responses": responses, "price": price} if price else responses
    script.write_text(json.dumps(data), encoding="utf-8")
    sleeps = []
    client = llm.make_client(f"fake:{script}", sleep=sleeps.append, **kw)
    return client, sleeps


USER = [{"role": "user", "content": "hi"}]


def test_fake_chat_round_trip_and_request_shape(tmp_path):
    client, _ = fake(tmp_path, [{"text": "hello", "usage": {"in": 50, "cached": 10, "out": 5}, "model": "fake-7"}])
    tools = [{"type": "function", "function": {"name": "check", "parameters": {"type": "object", "properties": {}}}}]
    resp = client.chat(USER, tools=tools)
    assert resp.text == "hello" and resp.tool_calls == [] and resp.model == "fake-7"
    assert (resp.tokens_in, resp.tokens_cached, resp.tokens_out) == (50, 10, 5)
    body = client.transport.requests[0]["body"]
    assert client.transport.requests[0]["path"] == "/chat/completions"
    assert body["temperature"] == 0 and body["model"] == str(tmp_path / "script.json")
    assert body["tools"] == tools and body["tool_choice"] == "auto"
    assert body["max_tokens"] == llm.MAX_TOKENS


def test_tool_calls_parsed_with_raw_arguments(tmp_path):
    client, _ = fake(tmp_path, [{"tool_calls": [{"name": "look", "arguments": {"view": "proof"}},
                                                 {"name": "check", "arguments": "{oops"}]}])
    resp = client.chat(USER)
    assert [c.name for c in resp.tool_calls] == ["look", "check"]
    assert json.loads(resp.tool_calls[0].arguments) == {"view": "proof"}
    assert resp.tool_calls[1].arguments == "{oops"  # passed through; the agent answers it
    assert resp.message["role"] == "assistant" and len(resp.message["tool_calls"]) == 2


def test_usage_counts_xai_reasoning_tokens_and_matches_xais_own_cost(tmp_path):
    # The usage block of a real grok-4.3 agent turn (17 Oct 2026): reasoning tokens sit outside
    # completion_tokens (total = prompt + completion + reasoning), and xAI reports its own cost.
    usage = {"prompt_tokens": 2025, "completion_tokens": 6, "total_tokens": 2234,
             "prompt_tokens_details": {"text_tokens": 2025, "image_tokens": 0, "cached_tokens": 128},
             "completion_tokens_details": {"reasoning_tokens": 203}, "cost_in_usd_ticks": 29193500}
    raw = {"model": "grok-4.3", "choices": [{"message": {"role": "assistant", "content": ""}, "finish_reason": "stop"}],
           "usage": usage}
    client, _ = fake(tmp_path, [raw], price=vars(spend.price_for("xai:grok-4.3")))
    resp = client.chat(USER)
    assert (resp.tokens_in, resp.tokens_cached, resp.tokens_out) == (2025, 128, 209)
    assert resp.cost_usd == pytest.approx(0.00291935, abs=1e-9)
    assert client.calls[0]["cost_reported_usd"] == pytest.approx(resp.cost_usd, abs=1e-6)


def test_listener_gets_a_record_with_the_request_hash(tmp_path):
    seen = []
    client, _ = fake(tmp_path, [{"text": "a"}], on_call=seen.append)
    resp = client.chat(USER, purpose="vision")
    body = client.transport.requests[0]["body"]
    payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
    assert seen[0]["request_sha256"] == hashlib.sha256(payload).hexdigest() == resp.request_sha256
    assert seen[0]["status"] == "ok" and seen[0]["purpose"] == "vision" and seen[0]["model_returned"] == "fake"
    assert {"tokens_in", "tokens_cached", "tokens_out", "cost_usd", "latency_ms", "attempts"} <= set(seen[0])
    assert client.calls == seen


def test_retries_429_and_5xx_with_backoff(tmp_path):
    client, sleeps = fake(tmp_path, [{"status": 429}, {"status": 503}, {"status": 500}, {"text": "ok"}])
    assert client.chat(USER).text == "ok"
    assert sleeps == [1.0, 2.0, 4.0]
    assert client.calls[-1]["attempts"] == 4


def test_gives_up_after_three_retries(tmp_path):
    client, sleeps = fake(tmp_path, [{"status": 500}] * 5)
    with pytest.raises(LLMError, match="HTTP 500"):
        client.chat(USER)
    assert len(client.transport.requests) == 4 and len(sleeps) == 3
    assert client.calls[-1]["status"] == "error"


def test_no_retry_on_4xx_or_timeout(tmp_path):
    client, sleeps = fake(tmp_path, [{"status": 400, "body": "bad request"}, {"timeout": True}])
    with pytest.raises(LLMError, match="HTTP 400: bad request"):
        client.chat(USER)
    with pytest.raises(LLMError, match="ReadTimeout"):
        client.chat(USER)
    assert sleeps == [] and len(client.transport.requests) == 2
    assert [c["status"] for c in client.calls] == ["error", "error"]


def test_budget_exceeded_before_any_request(tmp_path, ledger):
    spend.record("xai", "grok-4.3", 0, 0, 0, 0, 9.999, "earlier")
    client, _ = fake(tmp_path, [{"text": "never sent"}], price={"in_per_m": 1.25, "out_per_m": 2.50})
    with pytest.raises(BudgetExceeded):
        client.chat(USER)
    assert client.transport.requests == []
    assert client.calls[0]["status"] == "budget" and client.calls[0]["cost_usd"] == 0.0


def test_paid_calls_are_recorded_free_fake_calls_are_not(tmp_path, ledger):
    free, _ = fake(tmp_path, [{"text": "a"}])
    free.chat(USER)
    assert not ledger.exists()
    paid, _ = fake(tmp_path, [{"text": "a", "usage": {"in": 1000, "out": 100}}], price={"in_per_m": 1.25, "out_per_m": 2.5})
    paid.chat(USER, purpose="agent")
    (line,) = [json.loads(x) for x in ledger.read_text().splitlines()]
    assert line["purpose"] == "agent" and line["tokens_in"] == 1000
    assert line["usd"] == pytest.approx(0.0015)
    assert spend.ledger_total() == pytest.approx(paid.cost_usd)


class EchoKeyTransport(FakeTransport):
    secrets = ("xai-SECRETSECRET123",)

    def post(self, path, payload):
        self.requests.append({"path": path})
        return 401, {"error": {"message": "Incorrect API key provided: xai-SECRETSECRET123"}}, {}


def test_a_key_in_an_error_body_is_redacted():
    client = ChatClient("xai:grok-4.3", EchoKeyTransport([]), price=Price(), sleep=lambda s: None)
    with pytest.raises(LLMError) as exc:
        client.chat(USER)
    assert "SECRET" not in str(exc.value) and "[redacted]" in str(exc.value)
    assert "SECRET" not in json.dumps(client.calls)


def test_image_part_downscales_to_768_and_never_upscales():
    big = np.zeros((1000, 2000, 4), np.uint8)
    big[..., 3] = 255
    part = llm.image_part(big)
    assert part["type"] == "image_url"
    url = part["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    img = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
    assert img.size == (768, 384) and img.mode == "RGB"
    assert llm.prepare_image(Image.new("RGB", (300, 200))).size == (300, 200)


def test_prepare_image_flattens_alpha_onto_white():
    rgba = np.zeros((10, 10, 4), np.uint8)  # fully transparent black
    assert llm.prepare_image(rgba).getpixel((5, 5)) == (255, 255, 255)


def test_estimate_prompt_tokens_counts_images():
    msgs = [{"role": "user", "content": [{"type": "text", "text": "x" * 350}, {"type": "image_url", "image_url": {}}]}]
    assert llm.estimate_prompt_tokens(msgs) == int((350 + 16) / llm.CHARS_PER_TOKEN) + llm.IMAGE_TOKENS_ESTIMATE


def test_load_env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment\nexport PR_A=1\nPR_B = 'two words'\nPR_C=x # note\nPR_EMPTY=\nPR_SET=new\n", encoding="utf-8")
    monkeypatch.setenv("PR_SET", "old")
    for k in ("PR_A", "PR_B", "PR_C", "PR_EMPTY"):
        monkeypatch.delenv(k, raising=False)
    names = llm.load_env_file(env)
    assert names == ["PR_A", "PR_B", "PR_C"]  # names only, never values
    assert os.environ["PR_A"] == "1" and os.environ["PR_B"] == "two words" and os.environ["PR_C"] == "x"
    assert "PR_EMPTY" not in os.environ and os.environ["PR_SET"] == "old"
    for k in ("PR_A", "PR_B", "PR_C"):
        monkeypatch.delenv(k)


def test_make_client_real_provider_needs_key_and_price(tmp_path, monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    empty = tmp_path / "empty.env"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(LLMError, match="XAI_API_KEY is not set"):
        llm.make_client("xai:grok-4.3", env_file=empty)
    keyed = tmp_path / "key.env"
    keyed.write_text("XAI_API_KEY=xai-test-not-real\n", encoding="utf-8")
    client = llm.make_client("xai:grok-4.3", env_file=keyed)
    assert client.provider == "xai" and client.name == "grok-4.3" and isinstance(client.transport, llm.HttpTransport)
    assert client.transport._http.base_url.host == "api.x.ai"
    client.close()
    with pytest.raises(UnknownPrice):
        llm.make_client("xai:grok-unknown", env_file=keyed)
    with pytest.raises(ValueError, match="unknown provider"):
        llm.make_client("acme:model", env_file=keyed)
    monkeypatch.delenv("XAI_API_KEY")


def test_generate_image_through_the_spend_guard(tmp_path, ledger):
    png = io.BytesIO()
    Image.new("RGB", (4, 4), (255, 0, 0)).save(png, format="PNG")
    script = tmp_path / "img.json"
    script.write_text(json.dumps({"responses": [{"b64_json": base64.b64encode(png.getvalue()).decode()}],
                                  "price": {"per_image": 0.02}}), encoding="utf-8")
    raw = llm.generate_image(f"fake:{script}", "a cat sticker", aspect_ratio="1:1")
    assert raw == png.getvalue()
    (line,) = [json.loads(x) for x in ledger.read_text().splitlines()]
    assert line["images"] == 1 and line["usd"] == 0.02 and line["purpose"] == "image"
    spend.record("xai", "x", 0, 0, 0, 0, 9.99, "earlier")
    script.write_text(json.dumps({"responses": [{"b64_json": ""}], "price": {"per_image": 0.02}}), encoding="utf-8")
    with pytest.raises(BudgetExceeded):
        llm.generate_image(f"fake:{script}", "another")


def test_image_request_body(tmp_path):
    client, _ = fake(tmp_path, [{"b64_json": base64.b64encode(b"x").decode()}])
    assert client.image("a sticker") == b"x"
    req = client.transport.requests[0]
    assert req["path"] == "/images/generations"
    assert req["body"] | {"model": None} == {"model": None, "prompt": "a sticker", "n": 1,
                                             "response_format": "b64_json", "aspect_ratio": "1:1"}
    with pytest.raises(ValueError, match="xAI only"):
        llm.generate_image("openai:gpt-image-1", "x")
