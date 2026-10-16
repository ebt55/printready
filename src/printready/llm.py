"""One OpenAI-compatible chat client plus a fake provider for tests (chunk K4).

Model ids are `<provider>:<model>`: openrouter, xai, openai, or fake:<script> which replays
scripted responses. Keys come from the environment only. Every call is logged to JSONL before its
result is used; refusals, errors and parse failures are logged outcomes, never dropped.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

DEFAULT_MODEL = "openrouter:x-ai/grok-4.7"

# provider -> (base URL, environment variable that holds the key)
PROVIDERS: dict[str, tuple[str, str]] = {
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "xai": ("https://api.x.ai/v1", "XAI_API_KEY"),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
}


class ChatClient(Protocol):
    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """One chat-completions call at temperature 0; returns the parsed response."""
        ...


def make_client(model: str, log_path: Path | None = None) -> ChatClient:
    """Build a client for `model`, e.g. "openrouter:x-ai/grok-4.7" or "fake:<script>"."""
    raise NotImplementedError("K4")


def load_env_file(path: Path) -> None:
    """Load KEY=VALUE lines from a dotenv file into os.environ without overwriting set values."""
    raise NotImplementedError("K4")
