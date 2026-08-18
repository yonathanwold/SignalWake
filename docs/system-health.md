# System health and observability

SIGNALWAKE exposes operational telemetry from the running API. It is intended
for local inspection and a small deployment, not as a replacement for a
retained metrics backend.

## Endpoints

- `GET /health` is the compatibility platform summary. It includes database
  connectivity, source counts, overall state, process version, and uptime.
- `GET /health/live` is dependency-free and returns `alive` when the process can
  answer a request.
- `GET /health/ready` runs `SELECT 1` on the configured database and checks that
  startup initialization completed. It returns HTTP 503 until both checks pass.
- `GET /health/sources` returns the bounded event and infrastructure source
  matrix.
- `GET /metrics` combines bounded process-local request metrics with persisted
  `TransformationRun` summaries and the source matrix.

The API accepts an `X-Request-ID` header, or generates one. The same ID is
returned on the response and bound to structured logs. Request bodies, source
payloads, credentials, and authorization material are never stored in this
registry.

## Health states

The compatibility `health` value remains `HEALTHY`, `STALE`, `ERROR`, or
`UNKNOWN`. The operational state is explicit:

- `ACTIVE`: a successful source run is within its configured
  `expected_update_interval_seconds`.
- `DEGRADED`: the last success is older than that interval (or the one-hour
  fallback when no interval is configured), or a successful run rejected
  records / has a recent failure.
- `DOWN`: a source has an attempt/failure but no successful run.
- `UNKNOWN`: no source attempt or success telemetry exists.

The matrix includes last success, attempt, and failure timestamps, a freshness
value and threshold, received/accepted/rejected counts, adapter version, the
latest transformation run ID, and bounded error category/message.

## Metric scope and limits

Request count, error count/rate, status counts, latency, endpoint aggregates,
uptime, and the recent request incident deque are `process_local`; they reset
when the API process restarts. Endpoint cardinality is capped at 100 and
recent incidents at 50. Persisted processing summaries are read from at most
the newest 200 `TransformationRun` rows and grouped by run kind. The metrics
response returns at most 100 combined recent failures.

Transformation latency is derived from actual `started_at` and `completed_at`
timestamps for ingest, infrastructure import, assessment, relationship
derivation, and scenario runs. Replay and all other API latency comes from the
request middleware. There is no permanent worker or scheduler; startup ingest
is one bounded pass.

## Local inspection

```powershell
cd apps/api
python -m pytest -q
uvicorn app.main:app --reload --port 8000
Invoke-RestMethod http://localhost:8000/health | ConvertTo-Json -Depth 8
Invoke-RestMethod http://localhost:8000/metrics | ConvertTo-Json -Depth 10
```

The process-local registry is intentionally not a durable audit log. For
long-term alerting or fleet-wide aggregation, add an actual deployment need
and a retained backend rather than inferring enterprise metrics from this
bounded view.
