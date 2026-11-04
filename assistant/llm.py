"""The one place that talks to Claude.

Every caller must pass text that has already been through assistant.redaction.
Model: Claude Sonnet 5.5 by default (set ASSISTANT_MODEL to change).
Each call's token usage and estimated cost is appended to data/state/usage.jsonl.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

MODEL = os.environ.get("ASSISTANT_MODEL", "claude-sonnet-5-5")
# USD per million tokens (Claude API list prices for Sonnet 5.5).
PRICES = {"input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50}
USAGE_LOG = Path(os.environ.get("ASSISTANT_STATE_DIR", Path(__file__).resolve().parent.parent / "data/state")) / "usage.jsonl"

_client = None
_lock = threading.Lock()


class AIUnavailable(RuntimeError):
    """No API key configured, or the API could not be reached."""


class AIRefused(RuntimeError):
    """Claude declined this request (stop_reason == "refusal")."""


def set_client(client) -> None:
    """Tests inject a fake client here."""
    global _client
    _client = client


def get_client():
    global _client
    if _client is None:
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            raise AIUnavailable("The AI features need ANTHROPIC_API_KEY to be set on the server.")
        import anthropic
        _client = anthropic.Anthropic()
    return _client


def available() -> bool:
    try:
        get_client()
        return True
    except AIUnavailable:
        return False


def _log_usage(feature: str, usage) -> None:
    if usage is None:
        return
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    row = {
        "t": time.strftime("%Y-%m-%dT%H:%M:%S"), "feature": feature, "model": MODEL,
        "input": usage.input_tokens, "output": usage.output_tokens,
        "cache_read": cache_read, "cache_write": cache_write,
    }
    row["usd"] = round((row["input"] * PRICES["input"] + row["output"] * PRICES["output"]
                        + cache_read * PRICES["cache_read"] + cache_write * PRICES["cache_write"]) / 1e6, 6)
    with _lock:
        USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with USAGE_LOG.open("a") as f:
            f.write(json.dumps(row) + "\n")


def usage_summary() -> dict:
    if not USAGE_LOG.exists():
        return {"calls": 0, "usd": 0.0, "by_feature": {}}
    rows = [json.loads(line) for line in USAGE_LOG.read_text().splitlines() if line.strip()]
    by: dict[str, dict] = {}
    for r in rows:
        b = by.setdefault(r["feature"], {"calls": 0, "usd": 0.0})
        b["calls"] += 1
        b["usd"] = round(b["usd"] + r["usd"], 4)
    return {"calls": len(rows), "usd": round(sum(r["usd"] for r in rows), 4), "by_feature": by}


def create(*, feature: str, system: str, messages: list, effort: str = "low", max_tokens: int = 8000,
           tools: list | None = None, schema: dict | None = None):
    """One Messages API call. Raises AIUnavailable / AIRefused instead of returning bad output."""
    import anthropic

    output_config: dict = {"effort": effort}
    if schema:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    kwargs = dict(
        model=MODEL, max_tokens=max_tokens, messages=messages, output_config=output_config,
        system=system, cache_control={"type": "ephemeral"},
    )
    if tools:
        kwargs["tools"] = tools
    if MODEL in ("claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-1"):
        # Server-side fallback: if a safety classifier declines (e.g. a false positive), the API
        # retries on a fallback model automatically. Claude API only.
        kwargs["betas"] = ["server-side-fallback-2026-07-01"]
        kwargs["fallbacks"] = "default"
    try:
        resp = get_client().beta.messages.create(**kwargs)
    except anthropic.AuthenticationError as e:
        raise AIUnavailable("The API key was rejected. Check ANTHROPIC_API_KEY.") from e
    except anthropic.APIConnectionError as e:
        raise AIUnavailable("Couldn't reach the AI service. Check the internet connection.") from e
    _log_usage(feature, getattr(resp, "usage", None))
    if resp.stop_reason == "refusal":
        raise AIRefused("The assistant couldn't help with this one. Please handle it directly.")
    return resp


def text_of(resp) -> str:
    return "".join(b.text for b in resp.content if b.type == "text")


def create_json(*, schema: dict, **kw) -> dict:
    resp = create(schema=schema, **kw)
    if resp.stop_reason == "max_tokens":
        raise AIUnavailable("The AI response was cut off. Try again.")
    return json.loads(text_of(resp))
