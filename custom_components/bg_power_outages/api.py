"""Shared parts of the operator clients: outage model, errors, HTTP access and text helpers."""

from __future__ import annotations

import asyncio
import html
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import aiohttp

from .const import CACHE_TTL, MAX_PERIOD_DAYS, RATE_LIMIT_BACKOFF, REQUEST_TIMEOUT, TIMEZONE

HEADERS = {"User-Agent": "Mozilla/5.0 (Home Assistant bg_power_outages)"}
# HTML and JSON answers are a few KB to a few hundred KB.
MAX_TEXT_BYTES = 8 * 1024 * 1024
HM_RE = re.compile(r"^(\d{1,2})[:.](\d{2})$")
LATIN_TO_CYRILLIC = str.maketrans("ABCEHKMOPTXY", "АВСЕНКМОРТХУ")

KIND_PLANNED = "planned"
KIND_UNPLANNED = "unplanned"
# Planned switching during which the supply may be disturbed, not necessarily interrupted.
KIND_POSSIBLE = "possible"


class OutageError(Exception):
    """Information could not be retrieved or parsed."""


class OutageFormatError(OutageError):
    """An answer was received but not understood (the site's format may have changed)."""


class OutageRateLimited(OutageError):
    """The operator refused too many requests; none is sent until retry_after seconds pass."""

    def __init__(self, message: str, retry_after: float) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def normalize(text: str) -> str:
    """Upper case with collapsed whitespace, the form used for matching.

    Latin letters that look like Cyrillic ones become Cyrillic: published names contain them
    by mistake ("Бръшлeн" with a Latin e).
    """
    return re.sub(r"\s+", " ", text).strip().upper().translate(LATIN_TO_CYRILLIC)


def strip_tags(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


@dataclass(frozen=True, slots=True)
class Outage:
    """One outage: a published schedule row or a registration for a client number."""

    oblast: str
    district: str
    # Place name (ЕРМ Запад) or the published description of the affected area.
    place: str
    start: datetime
    end: datetime | None  # None: no (valid) expected restore time
    kind: str = KIND_PLANNED
    point: str = ""

    def matches(self, place: str, district: str = "", text: str = "") -> bool:
        """Place, district and text (if given) are case-insensitive substrings."""
        area = normalize(self.place)
        return (
            normalize(place) in area
            and (not district or normalize(district) in normalize(self.district))
            and (not text or normalize(text) in area)
        )

    def as_dict(self) -> dict[str, str | None]:
        data = {
            "place": self.place,
            "district": self.district,
            "oblast": self.oblast,
            "start": self.start.isoformat(),
            "end": self.end.isoformat() if self.end else None,
            "kind": self.kind,
        }
        if self.point:
            data["point"] = self.point
        return data


def parse_time(value: str) -> datetime:
    """'13.11.2026 09:15' (Europe/Sofia)."""
    return datetime.strptime(value.strip(), "%d.%m.%Y %H:%M").replace(tzinfo=TIMEZONE)


def parse_date(value: str) -> date:
    """'13.11.2026' or '2.11.2026'."""
    return datetime.strptime(value.strip(), "%d.%m.%Y").replace(tzinfo=TIMEZONE).date()


def _minutes(value: str) -> int:
    m = HM_RE.match(value.strip())
    if not m or int(m.group(1)) > 24 or int(m.group(2)) > 59:
        raise ValueError(f"not a time of day: {value!r}")
    return int(m.group(1)) * 60 + int(m.group(2))


def daily_windows(
    first: date, last: date, windows: list[tuple[str, str]]
) -> list[tuple[datetime, datetime]]:
    """A published period as one (start, end) per day and window.

    "16.11–20.11, 9:00–17:00" means 9:00–17:00 on each of these days. A window that does not end
    after it starts (22:00–06:00) ends on the next day. Periods longer than MAX_PERIOD_DAYS are cut.
    """
    spans = [(_minutes(a), _minutes(b)) for a, b in windows]
    out: list[tuple[datetime, datetime]] = []
    days = min((last - first).days, MAX_PERIOD_DAYS - 1)
    for offset in range(days + 1):
        day = first + timedelta(days=offset)
        midnight = datetime(day.year, day.month, day.day, tzinfo=TIMEZONE)
        for begin, end in spans:
            finish = end if end > begin else end + 24 * 60
            out.append((midnight + timedelta(minutes=begin), midnight + timedelta(minutes=finish)))
    return out


class OutageSource(ABC):
    """What one config entry monitors: planned outages and, if available, current ones."""

    # Whether async_current() reports outages registered right now.
    has_current = False
    # Whether async_current() also reports planned outages in progress; if not, a planned outage
    # counts as current while its published time window lasts.
    current_includes_planned = False

    async def async_current(self) -> list[Outage]:
        """Outages registered right now."""
        return []

    @abstractmethod
    async def async_planned(self) -> list[Outage]:
        """Published planned outages from yesterday on."""


class OperatorClient:
    """HTTP access to one operator's site, shared by all config entries of that operator.

    One request at a time; after a refusal for too many requests none is sent for
    RATE_LIMIT_BACKOFF. Downloads used by several entries are cached for CACHE_TTL.
    """

    name = ""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        run_blocking: Callable[..., Awaitable[Any]] = asyncio.to_thread,
    ) -> None:
        self._session = session
        self._run_blocking = run_blocking
        self._request_lock = asyncio.Lock()
        self._cache_lock = asyncio.Lock()
        self._cache: dict[str, tuple[float, Any]] = {}
        self._blocked_until = 0.0

    async def _cached[T](self, key: str, fetch: Callable[[], Awaitable[T]]) -> T:
        async with self._cache_lock:
            hit = self._cache.get(key)
            if hit and time.monotonic() - hit[0] < CACHE_TTL.total_seconds():
                value: T = hit[1]
                return value
            value = await fetch()
            self._cache[key] = (time.monotonic(), value)
            return value

    def _refused(self, body: bytes) -> bool:
        """Whether a 200 answer is a refusal for too many requests."""
        return False

    def _block(self, message: str) -> OutageRateLimited:
        backoff = RATE_LIMIT_BACKOFF.total_seconds()
        self._blocked_until = time.monotonic() + backoff
        return OutageRateLimited(message, backoff)

    async def _request(
        self,
        url: str,
        label: str,
        *,
        data: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        limit: int = MAX_TEXT_BYTES,
    ) -> bytes:
        """GET, or POST of a form when data is given."""
        method = "GET" if data is None else "POST"
        async with self._request_lock:
            if (wait := self._blocked_until - time.monotonic()) > 0:
                raise OutageRateLimited(
                    f"{label} not sent: {self.name} refused requests, waiting {wait:.0f} s", wait
                )
            try:
                async with self._session.request(
                    method,
                    url,
                    data=data,
                    headers=HEADERS | (headers or {}),
                    timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                ) as resp:
                    if resp.status == 429:
                        raise self._block(f"rate limited by {self.name} (HTTP 429)")
                    resp.raise_for_status()
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in resp.content.iter_chunked(65536):
                        size += len(chunk)
                        if size > limit:
                            raise OutageError(f"{label} answer larger than {limit} bytes")
                        chunks.append(chunk)
            except (aiohttp.ClientError, TimeoutError) as err:
                raise OutageError(f"request {label} failed: {err}") from err
            body = b"".join(chunks)
            if self._refused(body):
                raise self._block(f"rate limited by {self.name}")
        return body
