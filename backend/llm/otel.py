"""Optional OpenTelemetry export of LLM calls (spans + metrics over OTLP/HTTP).

Enabled when OTEL_EXPORTER_OTLP_ENDPOINT is set and requirements-otel.txt is
installed. Uses the GenAI semantic conventions (gen_ai.*), so Datadog, Grafana,
Honeycomb, Jaeger etc. can chart tokens and latency per provider/model.
"""

import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)


def make_sink(span_exporter=None, metric_reader=None):
    """Return a tracing sink, or None when OpenTelemetry isn't enabled/installed.

    The exporter arguments exist for tests; by default OTLP/HTTP exporters are
    used, configured through the standard OTEL_* environment variables.
    """
    if span_exporter is None and not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return None
    try:
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.trace import SpanKind, Status, StatusCode
    except ImportError:
        logger.warning(
            "OTEL_EXPORTER_OTLP_ENDPOINT is set but OpenTelemetry isn't installed — "
            "run `pip install -r requirements-otel.txt` to export LLM usage"
        )
        return None

    if span_exporter is None:
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        span_exporter = OTLPSpanExporter()
        metric_reader = PeriodicExportingMetricReader(OTLPMetricExporter())

    # OTEL_SERVICE_NAME / OTEL_RESOURCE_ATTRIBUTES win when set.
    resource = Resource.create({} if os.getenv("OTEL_SERVICE_NAME") else {"service.name": "repo-admin-backend"})
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    tracer = tracer_provider.get_tracer("repo-admin.llm")
    meter = MeterProvider(resource=resource, metric_readers=[metric_reader] if metric_reader else []).get_meter(
        "repo-admin.llm"
    )

    token_usage = meter.create_histogram("gen_ai.client.token.usage", unit="{token}", description="Tokens per LLM call")
    duration = meter.create_histogram("gen_ai.client.operation.duration", unit="s", description="LLM call duration")
    cost = meter.create_counter("llm.cost", unit="USD", description="Estimated LLM spend")
    calls = meter.create_counter("llm.calls", unit="{call}", description="LLM calls by outcome")

    def sink(record):
        attrs = {
            "gen_ai.operation.name": "chat",
            "gen_ai.provider.name": record.provider,
            "gen_ai.request.model": record.model,
            "app.feature": record.feature,
        }
        total_input = record.input_tokens + record.cache_read_tokens + record.cache_write_tokens

        start_ns = int(datetime.fromisoformat(record.started_at).timestamp() * 1e9)
        span = tracer.start_span(
            f"chat {record.model}",
            kind=SpanKind.CLIENT,
            start_time=start_ns,
            attributes={
                **attrs,
                "gen_ai.usage.input_tokens": total_input,
                "gen_ai.usage.output_tokens": record.output_tokens,
                "gen_ai.usage.cache_read.input_tokens": record.cache_read_tokens,
                "gen_ai.usage.cache_creation.input_tokens": record.cache_write_tokens,
                "llm.request_id": record.request_id,
                "llm.attempt": record.attempt,
                "llm.status": record.status,
                "llm.usage.estimated": record.estimated,
                **({"llm.cost.usd": record.cost_usd} if record.cost_usd is not None else {}),
                **({"llm.time_to_first_token_ms": record.ttft_ms} if record.ttft_ms is not None else {}),
                **({"session.id": record.session_id} if record.session_id else {}),
            },
        )
        if record.status == "error":
            span.set_attribute("error.type", "LLMError")
            span.set_status(Status(StatusCode.ERROR, record.error))
        span.end(end_time=start_ns + int(record.latency_ms * 1e6))

        token_usage.record(total_input, {**attrs, "gen_ai.token.type": "input"})
        token_usage.record(record.output_tokens, {**attrs, "gen_ai.token.type": "output"})
        duration.record(record.latency_ms / 1000, attrs)
        calls.add(1, {**attrs, "llm.status": record.status})
        if record.cost_usd is not None:
            cost.add(record.cost_usd, attrs)

    sink.tracer_provider = tracer_provider  # exposed so tests can force_flush
    return sink
