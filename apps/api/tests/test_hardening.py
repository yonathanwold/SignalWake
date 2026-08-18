import json
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.derivation import rebuild_derived_relationships
from app.graph import GraphEdge, GraphEngine, GraphNode
from app.graph_repository import list_relationship_edges
from app.infrastructure_import import (
    MAX_IMPORT_BYTES,
    _read_remote_json,
    _validate_remote_url,
    import_payload,
    load_payload,
)
from app.main import app

FIXTURES = Path(__file__).parents[1] / "app" / "fixtures"


def test_cors_settings_reject_wildcard_with_credentials():
    with pytest.raises(ValueError, match="wildcard"):
        Settings(cors_origins="*", cors_allow_credentials=True)
    settings = Settings(cors_origins="*", cors_allow_credentials=False)
    assert settings.cors_origin_list == ["*"]


def test_usgs_default_uses_past_day_feed(monkeypatch):
    monkeypatch.delenv("USGS_EARTHQUAKE_URL", raising=False)
    settings = Settings(_env_file=None)
    assert settings.usgs_earthquake_url.endswith("/summary/all_day.geojson")


def test_remote_url_rejects_private_and_unsafe_targets():
    for value in (
        "file:///etc/passwd",
        "http://127.0.0.1/data.json",
        "http://169.254.169.254/latest/meta-data",
        "http://localhost/data.json",
        "https://user:pass@93.184.216.34/data.json",
    ):
        with pytest.raises(ValueError):
            _validate_remote_url(value)


@pytest.mark.asyncio
async def test_remote_json_redirects_are_revalidated_and_payload_is_bounded():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=False
    ) as client:
        with pytest.raises(ValueError, match="not allowed"):
            await _read_remote_json(client, "https://93.184.216.34/source.json")

    assert calls == ["https://93.184.216.34/source.json"]

    def oversized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-length": str(MAX_IMPORT_BYTES + 1)}, content=b"{}"
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(oversized), follow_redirects=False
    ) as client:
        with pytest.raises(ValueError, match="exceeds"):
            await _read_remote_json(client, "https://93.184.216.34/source.json")


@pytest.mark.asyncio
async def test_importer_does_not_trust_proxy_environment(monkeypatch):
    observed: dict[str, object] = {}
    real_client = httpx.AsyncClient

    class CapturingClient:
        def __init__(self, **kwargs):
            observed.update(kwargs)
            self._client = real_client(
                transport=httpx.MockTransport(
                    lambda _request: httpx.Response(200, json={"features": []})
                ),
                **kwargs,
            )

        async def __aenter__(self):
            await self._client.__aenter__()
            return self._client

        async def __aexit__(self, *args):
            return await self._client.__aexit__(*args)

    monkeypatch.setattr("app.infrastructure_import.httpx.AsyncClient", CapturingClient)
    payload = await load_payload(url="https://93.184.216.34/source.json")
    assert payload == {"features": []}
    assert observed["trust_env"] is False


@pytest.mark.asyncio
async def test_security_headers_and_request_id_are_present():
    app.state.session_factory = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/health/live",
            headers={"Origin": "http://localhost:3000", "X-Request-ID": "hardening-test"},
        )
    assert response.status_code == 200
    assert response.headers["x-request-id"] == "hardening-test"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


@pytest.mark.asyncio
async def test_relationship_pages_return_one_statement_totals(db_factory):
    async with db_factory() as session:
        for filename, source_key in (
            ("infrastructure_ports.geojson", "bts_ports"),
            ("infrastructure_rail.geojson", "fra_rail"),
        ):
            payload = json.loads((FIXTURES / filename).read_text(encoding="utf-8"))
            await import_payload(session, source_key, payload)
        await rebuild_derived_relationships(session)
        first, total, next_cursor = await list_relationship_edges(session, limit=1)
        assert first
        if next_cursor is not None:
            second, second_total, _ = await list_relationship_edges(
                session, limit=1, cursor=next_cursor
            )
        else:
            second, second_total = [], total
        _, out_of_range_total, out_of_range_cursor = await list_relationship_edges(
            session, limit=1, cursor=999
        )
    assert total == second_total
    assert out_of_range_total == total
    assert out_of_range_cursor is None
    if next_cursor is not None:
        assert second
        assert first[0].id != second[0].id
    else:
        assert total == len(first)


def test_graph_metrics_are_memoized_per_engine(monkeypatch):
    engine = GraphEngine(
        [GraphNode("a"), GraphNode("b"), GraphNode("c")],
        [GraphEdge("ab", "a", "b", "CONNECTED_TO"), GraphEdge("bc", "b", "c", "CONNECTED_TO")],
    )
    calls: list[str] = []
    original = engine._alternate_path_count

    def counted(node_id, relationship_types=None):
        calls.append(node_id)
        return original(node_id, relationship_types)

    monkeypatch.setattr(engine, "_alternate_path_count", counted)
    first = engine.metrics("b")
    assert calls == ["b"]
    second = engine.metrics("a")
    assert calls == ["b", "a"]
    assert first["is_articulation_point"] is True
    assert second["component_size"] == 3
    assert len(engine._metrics_cache) == 1
    assert len(engine._alternate_path_cache[()]) == 2
