"""ЕРМ Запад (Electrohold distribution, western Bulgaria).

Undocumented endpoints of https://info.ermzapad.bg/webint/vok/avplan.php (POST unless noted):
  GET                                 -> HTML page; lists the municipalities with an outage right
                                         now: show_obstina('<code>','<oblast code>') … община <name>
  action=draw&gm_obstina=<code>       -> JSON {"1": {typedist, begin_event, end_event, city_name,
                                         …}, …}: planned and unplanned outages of the municipality
                                         registered right now
  action=showpdf                      -> HTML list of daily PDFs, previewdoc(<id>) + date badge
  action=showdocid&doc_id=<id>        -> PDF "Планирани прекъсвания за DD.MM.YYYY" (by place)
  action=chkca&itn=<client number>    -> JSON {"cnt": n, "ca": ["<32Z… point> <address>", …]}
  action=viewitn&itn=<client number>  -> HTML, outage registered right now (planned or unplanned)
  action=viewitn_plan&itn=<number>    -> HTML, planned outages in the next 48 hours (excludes a
                                         running one)
The per-point variants (viewpod, viewpod_plan with pod=32Z…) exist, but viewpod_plan ignores the
point (answers "За точка на измерване  към …"), so only the 12-digit client number is used.
The server answers "tomuch" above roughly 100 requests; the period and whether it is per IP are
not known.
"""

from __future__ import annotations

import asyncio
import json
import re
import zlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from ..api import (
    KIND_PLANNED,
    KIND_UNPLANNED,
    OperatorClient,
    Outage,
    OutageFormatError,
    OutageSource,
    normalize,
    parse_time,
    strip_tags,
)
from ..const import PARSE_TIMEOUT, TIMEZONE
from .erm_zapad_pdf import schedule_rows

URL = "https://info.ermzapad.bg/webint/vok/avplan.php"
CHECK_URL = "https://info.ermzapad.bg/webint/vok/avplan.php?BBKING=FYI"
PLAN_URL = "https://info.ermzapad.bg/webint/vok/avplan.php?PLAN=FYI"

LIST_RE = re.compile(r"previewdoc\((\d+)\);\">[^<]*</a>\s*<span[^>]*>(\d{2}\.\d{2}\.\d{4})<")
MUNICIPALITY_RE = re.compile(
    r"show_obstina\('([A-Z]{3}\d{2})','[A-Z]{3}'\)[^>]*>(?:\s*<[^>]*>)*\s*община\s+([^<]+?)\s*<"
)
CLIENT_NUMBER_RE = re.compile(r"^\d{12}$")
POINT_RE = re.compile(r"32Z[0-9A-Z]{13}")
TIME_RE = re.compile(r"(\d{2}\.\d{2}\.\d{4} \d{2}:\d{2})")
NO_OUTAGE_RE = re.compile(r"\bняма\s+(?:регистрирано|планирани)", re.I)
# Outage map place names of ambiguous villages carry the municipality: "ЯБЛАНИЦА, общ. Своге".
CITY_SUFFIX_RE = re.compile(r",\s*общ\..*$", re.I | re.S)
# A schedule PDF is a few hundred KB.
MAX_PDF_BYTES = 10 * 1024 * 1024
# Municipalities whose current outages are fetched for one place entry.
MAX_MUNICIPALITIES = 3
# Malformed input surfaces as one of these from the parsers.
PARSE_ERRORS = (
    ValueError,
    KeyError,
    IndexError,
    AttributeError,
    TypeError,
    RecursionError,
    zlib.error,
)


def redact(text: str) -> str:
    """Hide client numbers and metering points in texts that end up in logs or issues."""
    return POINT_RE.sub("32Z…", re.sub(r"\b\d{12}\b", "<client number>", text))


def mask_client_number(number: str) -> str:
    return f"…{number[-4:]}"


@dataclass(frozen=True, slots=True)
class MeteringPoint:
    point: str
    address: str


def parse_schedule(pdf: bytes) -> list[Outage]:
    """All outage rows of one daily schedule PDF.

    Rows that do not end after they start are dropped (HA calendars reject such events).
    """
    try:
        outages = [
            Outage(
                oblast=row["oblast"],
                district=row["district"],
                place=row["place"],
                start=parse_time(row["start"]),
                end=parse_time(row["end"]),
            )
            for row in schedule_rows(pdf)
        ]
    except PARSE_ERRORS as err:
        raise OutageFormatError(f"schedule PDF not readable: {err!r}") from err
    return [o for o in outages if o.end is not None and o.end > o.start]


def parse_municipalities(page: str) -> dict[str, str]:
    """Municipalities with an outage registered right now: code -> name."""
    if "show_obstina" not in page:
        raise OutageFormatError("outage page without the municipality list")
    return {code: name.strip() for code, name in MUNICIPALITY_RE.findall(page)}


def parse_events(body: str, municipality: str) -> list[Outage]:
    """draw answer -> outages registered right now (planned and unplanned)."""
    body = body.lstrip("\ufeff").strip()
    if not body:
        return []
    try:
        data = json.loads(body)
    except ValueError as err:
        raise OutageFormatError(f"unexpected outage map answer: {body[:200]!r}") from err
    items = data.values() if isinstance(data, dict) else data if isinstance(data, list) else None
    if items is None:
        raise OutageFormatError(f"unexpected outage map answer: {body[:200]!r}")
    outages = []
    for item in items:
        if not isinstance(item, dict) or not (m := TIME_RE.search(str(item.get("begin_event")))):
            continue
        try:
            start = parse_time(m.group(1))
            end_m = TIME_RE.search(str(item.get("end_event")))
            end = parse_time(end_m.group(1)) if end_m else None
        except ValueError as err:
            raise OutageFormatError(f"unreadable time in outage map answer: {err}") from err
        kind = KIND_PLANNED if str(item.get("typedist")) == "планирано" else KIND_UNPLANNED
        outages.append(
            Outage(
                "",
                municipality,
                CITY_SUFFIX_RE.sub("", str(item.get("city_name") or "")).strip(),
                start,
                end if end is not None and end > start else None,
                kind,
            )
        )
    return list(dict.fromkeys(outages))


def parse_points(body: str) -> list[MeteringPoint]:
    """chkca answer -> metering points with their address ("32Z… ЗЛАТУША ." -> ЗЛАТУША)."""
    try:
        data = json.loads(body.lstrip("\ufeff").strip())
    except ValueError as err:
        excerpt = redact(body[:200])
        raise OutageFormatError(f"unexpected client check answer: {excerpt!r}") from err
    items = data.get("ca") if isinstance(data, dict) else None
    points = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, str) and (m := POINT_RE.match(item.strip())):
            address = item.strip()[m.end() :].strip(" .,")
            points.append(MeteringPoint(m.group(0), re.sub(r"\s+", " ", address)))
    return points


def parse_client_outages(body: str, place: str) -> list[Outage]:
    """viewitn / viewitn_plan answer -> outages.

    Seen with an outage (2026-11-13):
      <strong>За клиентски номер N, на … има регистрирано прекъсване </strong><ul>
      <li>точка на измерване - 32Z…</li><ul><li>начало на прекъсването - 13.11.2026 09:15</li>
      <li>тип на прекъсването - планирано</li>
      <li>очаквано време за възстановяване - 13.11.2026 17:00</li></ul></ul>
    The planned (48 h) answer with outages has not been seen yet; it is parsed the same way, by
    "<label> - <value>" items. An answer with neither items nor a "no outage" sentence raises
    OutageFormatError with the (redacted) text.
    """
    body = body.lstrip("\ufeff").strip()
    outages: list[Outage] = []
    point = ""
    start: datetime | None = None
    end: datetime | None = None
    kind = KIND_PLANNED

    def flush() -> None:
        nonlocal start, end, kind
        if start is not None:
            valid_end = end if end is not None and end > start else None
            outages.append(Outage("", "", place, start, valid_end, kind, point))
        start, end, kind = None, None, KIND_PLANNED

    try:
        for item in re.findall(r"<li>(.*?)</li>", body, re.S):
            label, _, value = strip_tags(item).partition(" - ")
            label = label.strip().lower()
            if label.startswith("точка на измерване"):
                flush()
                point = value.strip()
            elif label.startswith("начало"):
                if start is not None:
                    flush()
                if m := TIME_RE.search(value):
                    start = parse_time(m.group(1))
            elif "възстановяване" in label or label.startswith("край"):
                if m := TIME_RE.search(value):
                    end = parse_time(m.group(1))
            elif label.startswith("тип"):
                kind = KIND_UNPLANNED if "непланирано" in value.lower() else KIND_PLANNED
        flush()
    except ValueError as err:
        raise OutageFormatError(f"unreadable time in outage answer: {err}") from err
    if outages:
        return outages
    text = strip_tags(body)
    if NO_OUTAGE_RE.search(text):
        return []
    raise OutageFormatError(f"unrecognised outage answer: {redact(text[:300])}")


class ErmZapadClient(OperatorClient):
    name = "ERM Zapad"

    def _refused(self, body: bytes) -> bool:
        return body.strip(b"\xef\xbb\xbf \t\r\n") == b"tomuch"

    async def _post(self, data: dict[str, str], limit: int | None = None) -> bytes:
        label = data.get("action", "")
        if limit is None:
            return await self._request(URL, label, data=data)
        return await self._request(URL, label, data=data, limit=limit)

    async def async_get_schedules(self) -> list[Outage]:
        """Schedule rows of all places from yesterday on."""
        return await self._cached("schedules", self._fetch_schedules)

    async def async_get_municipalities(self) -> dict[str, str]:
        """Municipalities with an outage registered right now: code -> name."""

        async def fetch() -> dict[str, str]:
            page = await self._request(URL, "outage page")
            return parse_municipalities(page.decode("utf-8", "replace"))

        return await self._cached("municipalities", fetch)

    async def async_get_events(self, code: str, municipality: str) -> list[Outage]:
        """Outages registered right now in one municipality."""

        async def fetch() -> list[Outage]:
            body = await self._post({"action": "draw", "gm_obstina": code, "lat": "0", "lon": "0"})
            return parse_events(body.decode("utf-8", "replace"), municipality)

        return await self._cached(f"draw|{code}", fetch)

    async def async_get_points(self, client_number: str) -> list[MeteringPoint]:
        """Metering points of a client number; empty for an unknown number."""
        body = await self._post({"action": "chkca", "itn": client_number})
        return parse_points(body.decode("utf-8", "replace"))

    async def async_get_client_current(self, client_number: str, place: str) -> list[Outage]:
        """Outage registered right now for the client number (planned or unplanned)."""
        body = await self._post(
            {"itn": client_number, "action": "viewitn", "user": "", "lat": "0", "lon": "0"}
        )
        return parse_client_outages(body.decode("utf-8", "replace"), place)

    async def async_get_client_planned(self, client_number: str, place: str) -> list[Outage]:
        """Planned outages for the client number in the next 48 hours."""
        body = await self._post(
            {"itn": client_number, "action": "viewitn_plan", "user": "", "lat": "0", "lon": "0"}
        )
        return parse_client_outages(body.decode("utf-8", "replace"), place)

    async def _fetch_schedules(self) -> list[Outage]:
        # Yesterday's schedule is kept for outages that run past midnight.
        since = datetime.now(TIMEZONE).date() - timedelta(days=1)
        listing = (await self._post({"action": "showpdf"})).decode("utf-8", "replace")
        entries = LIST_RE.findall(listing)
        if not entries:
            raise OutageFormatError("schedule list is empty or its format changed")
        docs: dict[date, int] = {}
        for doc_id, date_s in entries:
            try:
                day = datetime.strptime(date_s, "%d.%m.%Y").replace(tzinfo=TIMEZONE).date()
            except ValueError:
                continue
            if day >= since:
                docs[day] = max(int(doc_id), docs.get(day, 0))
        outages: list[Outage] = []
        for day in sorted(docs):
            pdf = await self._post(
                {"action": "showdocid", "doc_id": str(docs[day])}, limit=MAX_PDF_BYTES
            )
            if not pdf.startswith(b"%PDF"):
                raise OutageFormatError(f"schedule {docs[day]} for {day} is not a PDF")
            try:
                async with asyncio.timeout(PARSE_TIMEOUT):
                    outages.extend(await self._run_blocking(parse_schedule, pdf))
            except TimeoutError as err:
                message = f"schedule {docs[day]} for {day}: parsing timed out"
                raise OutageFormatError(message) from err
        return list(dict.fromkeys(outages))


class ClientNumberSource(OutageSource):
    """Exact for the client number's address, planned outages 48 hours ahead."""

    has_current = True
    current_includes_planned = True

    def __init__(self, client: ErmZapadClient, number: str, address: str) -> None:
        self._client = client
        self._number = number
        self._address = address

    async def async_current(self) -> list[Outage]:
        return await self._client.async_get_client_current(self._number, self._address)

    async def async_planned(self) -> list[Outage]:
        return await self._client.async_get_client_planned(self._number, self._address)


class PlaceSource(OutageSource):
    """Daily schedule rows of a place; unplanned outages only when the municipality is given."""

    def __init__(self, client: ErmZapadClient, place: str, district: str) -> None:
        self._client = client
        self._place = place
        self._district = district
        self.has_current = bool(district)

    async def async_current(self) -> list[Outage]:
        if not self._district:
            return []
        wanted = normalize(self._district)
        codes = [
            (code, name)
            for code, name in (await self._client.async_get_municipalities()).items()
            if wanted in normalize(name)
        ]
        outages: list[Outage] = []
        for code, name in codes[:MAX_MUNICIPALITIES]:
            outages.extend(
                o
                for o in await self._client.async_get_events(code, name)
                if o.kind == KIND_UNPLANNED and o.matches(self._place, self._district)
            )
        return outages

    async def async_planned(self) -> list[Outage]:
        return [
            o
            for o in await self._client.async_get_schedules()
            if o.matches(self._place, self._district)
        ]
