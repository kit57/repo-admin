"""Token, cost and latency tracing for every LLM call, whatever the provider.

Each call produces one CallRecord, which is handed to every registered sink
(JSON log line, SQLite, OpenTelemetry...). Sinks run after the stream ends, so
they add nothing to time-to-first-token, and a failing sink never breaks a request.
"""

import asyncio
import json
import logging
import math
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from . import otel, pricing
from .base import LLMError, LLMProvider, Usage

CHARS_PER_TOKEN = 4  # same rough estimate repo_parser uses

logger = logging.getLogger(__name__)
usage_logger = logging.getLogger("llm.usage")


@dataclass
class CallRecord:
    id: str
    request_id: str  # shared by every attempt (primary + fallbacks) of one request
    started_at: str  # ISO 8601, UTC
    provider: str
    model: str
    feature: str
    session_id: str | None
    attempt: int  # 0 = primary provider, 1+ = fallbacks
    status: str  # "ok" | "error" | "cancelled"
    error: str | None
    input_tokens: int  # uncached input
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    estimated: bool  # True when a token count was estimated from text length
    cost_usd: float | None  # None when the model has no known price
    latency_ms: float
    ttft_ms: float | None  # time to first token


Sink = Callable[[CallRecord], None]
_sinks: list[Sink] = []
_configured = False


def add_sink(sink: Sink) -> None:
    _sinks.append(sink)


def log_sink(record: CallRecord) -> None:
    usage_logger.info(json.dumps({"event": "llm_call", **asdict(record)}))


def configure_tracing(extra_sinks: list[Sink] = ()) -> None:
    """Register the built-in sinks (log line, OpenTelemetry if enabled) plus any extra ones."""
    global _configured
    if _configured:
        return
    _configured = True

    if (os.getenv("LLM_USAGE_LOG") or "true").lower() not in ("0", "false", "no"):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        usage_logger.addHandler(handler)
        usage_logger.setLevel(logging.INFO)
        usage_logger.propagate = False
        add_sink(log_sink)

    otel_sink = otel.make_sink()
    if otel_sink:
        add_sink(otel_sink)

    for sink in extra_sinks:
        add_sink(sink)


def _emit(record: CallRecord) -> None:
    for sink in _sinks:
        try:
            sink(record)
        except Exception:
            logger.exception("LLM usage sink %r failed", sink)


def _estimate_tokens(chars: int) -> int:
    return math.ceil(chars / CHARS_PER_TOKEN)


async def traced_stream(
    provider: LLMProvider,
    system: str,
    messages: list[dict],
    *,
    request_id: str,
    attempt: int,
    feature: str,
    session_id: str | None,
):
    """Wrap provider.stream, recording tokens, cost, latency and outcome when it finishes."""
    usage = Usage()
    started_at = datetime.now(timezone.utc).isoformat()
    start = time.perf_counter()
    ttft_ms = None
    output_chars = 0
    status, error = "ok", None
    try:
        async for token in provider.stream(system, messages, usage):
            if ttft_ms is None:
                ttft_ms = (time.perf_counter() - start) * 1000
            output_chars += len(token)
            yield token
    except (GeneratorExit, asyncio.CancelledError):
        status = "cancelled"  # e.g. the client disconnected mid-stream
        raise
    except Exception as e:
        status = "error"
        error = str(e) if isinstance(e, LLMError) else f"{type(e).__name__}: {e}"
        raise
    finally:
        # A call that failed before producing anything wasn't billed; anything else may have been.
        billed = usage.input_tokens is not None or ttft_ms is not None or status == "cancelled"
        if usage.input_tokens is not None:
            input_tokens = usage.input_tokens
        elif billed:
            input_chars = len(system) + sum(len(m["content"]) for m in messages)
            input_tokens = _estimate_tokens(input_chars)
        else:
            input_tokens = 0
        output_tokens = (
            usage.output_tokens if usage.output_tokens is not None else _estimate_tokens(output_chars)
        )
        estimated = (usage.input_tokens is None and billed) or (
            usage.output_tokens is None and output_chars > 0
        )

        price = pricing.lookup(provider.name, provider.model)
        cost = (
            price.cost(input_tokens, output_tokens, usage.cache_read_tokens, usage.cache_write_tokens)
            if price
            else None
        )

        _emit(
            CallRecord(
                id=str(uuid.uuid4()),
                request_id=request_id,
                started_at=started_at,
                provider=provider.name,
                model=provider.model,
                feature=feature,
                session_id=session_id,
                attempt=attempt,
                status=status,
                error=error,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=usage.cache_read_tokens,
                cache_write_tokens=usage.cache_write_tokens,
                estimated=estimated,
                cost_usd=cost,
                latency_ms=round((time.perf_counter() - start) * 1000, 1),
                ttft_ms=round(ttft_ms, 1) if ttft_ms is not None else None,
            )
        )
