"""Wall-clock datetimes stored as naive values in Africa/Cairo (SQLite-safe, no timezone=True)."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

CAIRO_TZ = ZoneInfo("Africa/Cairo")


def now_local() -> datetime:
    """Current instant as naive Cairo wall clock (same convention as all ORM datetime columns)."""
    return datetime.now(CAIRO_TZ).replace(tzinfo=None)


def today_cairo() -> date:
    """Current calendar date in Africa/Cairo (for bookings / dashboard 'today')."""
    return datetime.now(CAIRO_TZ).date()
