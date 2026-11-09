"""The only module that talks to the LLM. Follows the rules in docs/architecture.md."""

import logging
import os
import re
import threading
import time
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 120.0
_REQUIRED = ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")
_REASONING = re.compile(r"<think>.*?</think>", re.DOTALL)
_CITATIONS = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
_URL = re.compile(r"https?://\S+")


@dataclass(frozen=True)
class LLMReply:
    text: str
    model: str
    provider: str


class LLMError(Exception):
    """A failure the learner can recover from by retrying or fixing configuration."""

    def __init__(self, code: str, message: str, status_code: int = 503) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def invalid_output(message: str) -> LLMError:
    return LLMError("llm_invalid_output", message, 502)


LEARNER_HOURLY_LIMIT_ENV = "LLM_LEARNER_HOURLY_LIMIT"
GLOBAL_HOURLY_LIMIT_ENV = "LLM_HOURLY_LIMIT"
DEFAULT_LEARNER_HOURLY_LIMIT = 60
DEFAULT_GLOBAL_HOURLY_LIMIT = 300
_WINDOW_SECONDS = 3600.0
_calls: dict[int | None, deque[float]] = {}
_calls_lock = threading.Lock()


def _hourly_limit(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, "").strip() or default))
    except ValueError:
        return default


def reserve(learner_id: int) -> None:
    """Count one model request for the tutor, lessons, plan or lab assistant.

    Learner tokens are free to create, so the global limit is the real ceiling on cost.
    Refused requests don't count; failed ones do, since they may still have cost money.
    Question generation has its own limits, kept in the database (assessment/api.py).
    """
    # ponytail: in-process window, so it resets on restart and isn't shared between
    # workers. Fine for the single-process local setup; move to the database if the
    # backend ever runs more than one worker.
    learner_limit = _hourly_limit(
        LEARNER_HOURLY_LIMIT_ENV, DEFAULT_LEARNER_HOURLY_LIMIT
    )
    global_limit = _hourly_limit(GLOBAL_HOURLY_LIMIT_ENV, DEFAULT_GLOBAL_HOURLY_LIMIT)
    now = time.monotonic()
    with _calls_lock:
        for key in list(_calls):
            window = _calls[key]
            while window and window[0] <= now - _WINDOW_SECONDS:
                window.popleft()
            if not window:
                del _calls[key]
        mine = _calls.setdefault(learner_id, deque())
        everyone = _calls.setdefault(None, deque())
        if len(mine) >= learner_limit:
            message = f"You can use the AI model {learner_limit} times an hour."
        elif len(everyone) >= global_limit:
            message = "The AI model has reached its hourly limit."
        else:
            mine.append(now)
            everyone.append(now)
            return
    raise LLMError("llm_rate_limited", f"{message} Try again later.", 429)


def reset_limits() -> None:
    with _calls_lock:
        _calls.clear()


def _provider_label(base_url: str) -> str:
    """Host and port only, because a URL can carry credentials."""
    parts = urlsplit(base_url)
    host = parts.hostname or "unknown"
    return f"{host}:{parts.port}" if parts.port else host


def complete(messages: Sequence[ChatCompletionMessageParam]) -> LLMReply:
    settings = {name: os.environ.get(name, "").strip() for name in _REQUIRED}
    missing = [name for name, value in settings.items() if not value]
    if missing:
        raise LLMError(
            "llm_not_configured",
            f"The AI model is not configured. Set {', '.join(missing)} in .env.",
        )
    base_url, api_key, model = settings.values()
    try:
        timeout = float(os.environ.get("LLM_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    except ValueError:
        timeout = DEFAULT_TIMEOUT_SECONDS

    try:
        # Endpoint and key are explicit: left unset, the SDK would use OpenAI's URL.
        client = OpenAI(
            base_url=base_url, api_key=api_key, timeout=timeout, max_retries=1
        )
        response = client.chat.completions.create(model=model, messages=messages)
        content = response.choices[0].message.content if response.choices else None
    except Exception as exc:
        # Bad URLs and odd bodies from compatible servers surface as more than the SDK's
        # own errors, and all of them must reach the learner as a recoverable failure.
        # The detail stays in the log, since upstream errors can echo request data.
        log.warning("LLM request failed: %s", exc)
        raise LLMError(
            "llm_unavailable",
            "The AI model could not be reached or returned an error. "
            "Nothing was lost, so you can try again.",
        ) from exc

    text = _REASONING.sub("", content or "").strip()
    if not text:
        raise invalid_output("The AI model returned an empty response. Try again.")
    return LLMReply(text, model, _provider_label(base_url))


def clean_model_text(text: str, source_count: int) -> str:
    """Drop citations with no matching source and links nothing retrieved supplied.

    Sources are only ever numbered by the server, so a number outside that range and any
    URL can only be the model's invention.
    """

    def keep_valid(match: re.Match[str]) -> str:
        numbers = [part.strip() for part in match[1].split(",")]
        valid = [n for n in numbers if len(n) <= 3 and 1 <= int(n) <= source_count]
        return f"[{', '.join(valid)}]" if valid else ""

    return _URL.sub("[link removed]", _CITATIONS.sub(keep_valid, text)).strip()


def as_data(text: str) -> str:
    """Stop untrusted text from closing the tags that mark it as data in a prompt."""
    return text.replace("<", "&lt;").replace(">", "&gt;")
