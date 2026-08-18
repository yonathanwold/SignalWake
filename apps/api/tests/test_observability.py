from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.infrastructure_import import import_payload
from app.main import app
from app.models import InfrastructureSource, TransformationRun
from app.observability import MetricsRegistry, operational_state


def test_metrics_registry_is_deterministic_and_bounded():
    now = datetime(2026, 8, 17, 12, tzinfo=timezone.utc)
    registry = MetricsRegistry(clock=lambda: now)
    registry.record_request(
        method="get",
        route="/events/{event_id}",
        status_code=200,
        duration_ms=4,
        request_id="r1",
    )
    registry.record_request(
        method="GET",
        route="/events/{event_id}",
        status_code=404,
        duration_ms=8,
        request_id="r2",
        category="client_error",
    )
    snapshot = registry.snapshot()
    assert snapshot["requests"] == 2
    assert snapshot["errors"] == 1
    assert snapshot["error_rate"] == 0.5
    assert snapshot["endpoints"][0]["route"] == "/events/{event_id}"
    assert snapshot["recent_incidents"][0]["request_id"] == "r2"


def test_operational_states_use_expected_interval_and_failure_history():
    now = datetime(2026, 8, 17, 12, tzinfo=timezone.utc)
    success = now - timedelta(minutes=5)
    assert operational_state(last_success_at=success, last_attempt_at=success, last_failure_at=None, records_rejected=0, expected_interval_seconds=600, now=now) == "ACTIVE"
    assert operational_state(last_success_at=now - timedelta(minutes=20), last_attempt_at=success, last_failure_at=None, records_rejected=0, expected_interval_seconds=600, now=now) == "DEGRADED"
    assert operational_state(last_success_at=None, last_attempt_at=success, last_failure_at=success, records_rejected=0, expected_interval_seconds=None, now=now) == "DOWN"
    assert operational_state(last_success_at=None, last_attempt_at=None, last_failure_at=None, records_rejected=None, expected_interval_seconds=None, now=now) == "UNKNOWN"


@pytest.mark.asyncio
async def test_health_liveness_readiness_and_bounded_metrics(db_factory):
    app.state.session_factory = db_factory
    app.state.startup_ready = True
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        live = await client.get("/health/live")
        assert live.status_code == 200
        assert live.json()["status"] == "alive"

        ready = await client.get("/health/ready")
        assert ready.status_code == 200
        assert ready.json()["database"] == "connected"

        health = await client.get("/health")
        assert health.status_code == 200
        assert health.json()["database_state"] == "connected"

        matrix = await client.get("/health/sources")
        assert matrix.status_code == 200
        assert matrix.json()["items"] == []

        metrics = await client.get("/metrics", headers={"X-Request-ID": "observability-test"})
        assert metrics.status_code == 200
        body = metrics.json()
        assert body["process_local"]["collection_scope"] == "process_local"
        assert body["persisted_runs"]["collection_scope"] == "persisted_runs"
        assert len(body["process_local"]["endpoints"]) <= 100
        assert metrics.headers["X-Request-ID"] == "observability-test"


@pytest.mark.asyncio
async def test_invalid_infrastructure_payload_persists_failure_state(db_factory):
    async with db_factory() as session:
        report = await import_payload(session, "bts_ports", {"unexpected": []})
        assert report.fetched_count == 0
        source = await session.scalar(select(InfrastructureSource).where(InfrastructureSource.key == "bts_ports"))
        run = await session.scalar(select(TransformationRun))
        assert source is not None and source.last_error_category == "invalid_payload"
        assert run is not None and run.status == "failed" and run.error_category == "invalid_payload"
