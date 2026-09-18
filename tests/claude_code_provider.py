"""ClaudeCodeTestProvider - a TEST-ONLY transport shim.

WHY THIS EXISTS
    This environment has no ANTHROPIC_API_KEY, so `app/claude_client.py` (the
    intended production provider) cannot reach the API. This shim routes the
    same calls through the already-authenticated Claude Code CLI so the
    application's *behaviour* can be qualified.

WHAT IT DOES AND DOES NOT DO
    It duck-types the two Anthropic SDK methods the application calls:
        client.messages.create(...)  -> object with .content[].text
        client.messages.parse(...)   -> object with .parsed_output
    It is injected as `app.claude_client._client`, so `extract_facts()` and
    `draft_response()` run **unmodified production code** - identical system
    prompt, identical user prompt, identical control flow. Only the wire
    transport changes. No production file is edited.

    It does NOT read, extract, store, or forward any OAuth credential. It
    shells out to `claude`, which authenticates itself.

FIDELITY CAVEAT (important when reading results)
    `messages.create` is faithful: same system prompt, same user content.
    `messages.parse` is NOT fully faithful. The real SDK uses constrained
    decoding (`output_config.format`) to guarantee schema-valid JSON. The CLI
    has no such parameter, so this shim asks for JSON in the prompt and
    validates with the same Pydantic model afterwards. Extraction *content*
    is therefore representative; extraction *enforcement* is not the
    production mechanism and must be re-verified once an API key exists.

NOT FOR PRODUCTION. Per-call latency is seconds, not milliseconds.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any

DEFAULT_TIMEOUT = 120


class ClaudeCodeError(RuntimeError):
    """The CLI failed or returned nothing usable."""


@dataclass
class _TextBlock:
    text: str
    type: str = "text"


@dataclass
class _Response:
    content: list[_TextBlock]
    parsed_output: Any = None
    model: str | None = None
    latency_s: float = 0.0
    raw: str = ""


@dataclass
class _Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None


def _run_cli(system: str, user: str, model: str | None, timeout: int) -> tuple[str, float]:
    """One non-interactive CLI turn. Tools off, no session persistence."""
    import time

    cmd = ["claude", "-p", "--output-format", "text", "--no-session-persistence",
           "--allowed-tools", ""]
    if model:
        cmd += ["--model", model]
    cmd += ["--system-prompt", system, user]

    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise ClaudeCodeError(f"claude CLI timed out after {timeout}s") from exc
    elapsed = time.monotonic() - started

    if proc.returncode != 0:
        raise ClaudeCodeError(f"claude CLI exited {proc.returncode}: {proc.stderr[:300]}")
    out = proc.stdout.strip()
    if not out:
        raise ClaudeCodeError("claude CLI returned empty output")
    return out, elapsed


def _strip_fence(text: str) -> str:
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip()


class _Messages:
    def __init__(self, timeout: int) -> None:
        self._timeout = timeout
        self.calls: list[dict[str, Any]] = []

    @staticmethod
    def _flatten(system: Any, messages: list[dict]) -> tuple[str, str]:
        sys_text = system if isinstance(system, str) else "\n\n".join(
            b.get("text", "") for b in (system or [])
        )
        user_text = "\n\n".join(
            m["content"] if isinstance(m["content"], str) else json.dumps(m["content"])
            for m in messages
        )
        return sys_text, user_text

    def create(self, *, model=None, system=None, messages, **_ignored) -> _Response:
        sys_text, user_text = self._flatten(system, messages)
        out, secs = _run_cli(sys_text, user_text, model, self._timeout)
        self.calls.append({"kind": "create", "model": model, "latency_s": secs,
                           "system": sys_text, "user": user_text, "output": out})
        return _Response(content=[_TextBlock(text=out)], model=model,
                         latency_s=secs, raw=out)

    def parse(self, *, model=None, system=None, messages, output_format, **_ignored) -> _Response:
        sys_text, user_text = self._flatten(system, messages)
        schema = json.dumps(output_format.model_json_schema(), indent=2)
        sys_text = (
            f"{sys_text}\n\nReturn ONLY a JSON object conforming to this schema. "
            f"No prose, no code fence, no commentary.\n{schema}"
        )
        out, secs = _run_cli(sys_text, user_text, model, self._timeout)
        try:
            parsed = output_format.model_validate_json(_strip_fence(out))
        except Exception as exc:  # pydantic ValidationError or json error
            raise ClaudeCodeError(f"output did not validate against schema: {exc}") from exc
        self.calls.append({"kind": "parse", "model": model, "latency_s": secs,
                           "system": sys_text, "user": user_text, "output": out})
        return _Response(content=[_TextBlock(text=out)], parsed_output=parsed,
                         model=model, latency_s=secs, raw=out)


class ClaudeCodeTestProvider:
    """Duck-typed stand-in for `anthropic.Anthropic`. Test use only."""

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.messages = _Messages(timeout)

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self.messages.calls


def install(timeout: int = DEFAULT_TIMEOUT) -> ClaudeCodeTestProvider:
    """Point app.claude_client at this provider. Returns it for inspection."""
    from app import claude_client

    provider = ClaudeCodeTestProvider(timeout)
    claude_client._client = provider  # noqa: SLF001 - deliberate test injection
    return provider
