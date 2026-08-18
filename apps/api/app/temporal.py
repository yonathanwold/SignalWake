"""Explicit temporal rules for operational/live SIGNALWAKE surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import Select, and_, or_

from app.models import Event

LIVE_WINDOW_HOURS = 48
LIVE_WINDOW = timedelta(hours=LIVE_WINDOW_HOURS)


def as_utc(value: datetime) -> datetime:
    """Normalize aware and legacy-naive timestamps to UTC."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class TemporalWindow:
    start: datetime
    end: datetime
    hours: int = LIVE_WINDOW_HOURS

    def __post_init__(self) -> None:
        start = as_utc(self.start)
        end = as_utc(self.end)
        if end < start:
            raise ValueError("end_time must be at or after start_time")
        if end - start > LIVE_WINDOW:
            raise ValueError(f"operational event windows cannot exceed {LIVE_WINDOW_HOURS} hours")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "hours", max(1, int((end - start).total_seconds() // 3600)))


def resolve_live_window(
    start: datetime | None = None,
    end: datetime | None = None,
    *,
    now: datetime | None = None,
    require_recent: bool = False,
) -> TemporalWindow:
    """Resolve an optional bounded API range, defaulting to the last 48 hours."""

    now_utc = as_utc(now or datetime.now(timezone.utc))
    if start is None and end is None:
        return TemporalWindow(now_utc - LIVE_WINDOW, now_utc)
    if end is None:
        end = as_utc(start) + LIVE_WINDOW if start is not None else now_utc
    if start is None:
        start = as_utc(end) - LIVE_WINDOW
    window = TemporalWindow(start, end)
    if window.end > now_utc:
        raise ValueError("operational event windows cannot extend into the future")
    if require_recent and window.start < now_utc - LIVE_WINDOW:
        raise ValueError(f"operational event windows must be within the past {LIVE_WINDOW_HOURS} hours")
    return window


def event_in_window(statement: Select, window: TemporalWindow) -> Select:
    """Filter events whose source time, receipt time, or validity overlaps a window.

    ``expires_at IS NULL`` is an open validity interval. It is intentionally
    included only when the event's effective time is before the window end; no
    records are generated for sources without data.
    """

    start, end = window.start, window.end
    def in_window(column):
        return and_(column >= start, column <= end)
    validity_overlap = and_(
        Event.effective_at.is_not(None),
        Event.effective_at <= end,
        or_(Event.expires_at.is_(None), Event.expires_at >= start),
    )
    return statement.where(
        or_(in_window(Event.observed_at), in_window(Event.received_at), in_window(Event.effective_at), validity_overlap)
    )


def temporal_metadata(window: TemporalWindow, *, generated_at: datetime | None = None) -> dict[str, object]:
    return {
        "window_start": window.start,
        "window_end": window.end,
        "window_hours": LIVE_WINDOW_HOURS,
        "temporal_semantics": "observed/effective/received timestamps in window or validity interval overlaps window",
        "generated_at": as_utc(generated_at or datetime.now(timezone.utc)),
    }
