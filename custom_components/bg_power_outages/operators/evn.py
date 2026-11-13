"""Електроразпределение Юг (EVN, south-eastern Bulgaria).

Undocumented pages of https://www.elyug.bg:
  GET /oldservices/ec_ep/abschaltung_bg/abschaltung<1-9>.asp
    -> HTML (windows-1251), planned outages of one province as label/value table rows:
       Област, КЕЦ, Адрес(и), Срок на изключването от / до ("09:00 - 16:30"),
       Дата(и) на изключването ("2.11.2026 до 20.11.2026", the hours apply on each day)
  GET /Customers/Unscheduled-power-cuts.aspx, then POST it back with the ASP.NET form fields and
  __EVENTTARGET/__EVENTARGUMENT of the province's map area
    -> HTML, unplanned outages known right now: Област, Описание, Дата на изключване от
       ("13.11.2026 г.", seen without a time), Очакван срок на отстраняване (seen empty)
There is no public check by client number.
"""

from __future__ import annotations

import html
import re
from datetime import datetime

from ..api import (
    KIND_UNPLANNED,
    OperatorClient,
    Outage,
    OutageError,
    OutageFormatError,
    OutageSource,
    daily_windows,
    normalize,
    parse_date,
    strip_tags,
)
from ..const import TIMEZONE

PAGE_URL = "https://www.elyug.bg/Customers/Planned_shutdowns.aspx"
PLANNED_URL = "https://www.elyug.bg/oldservices/ec_ep/abschaltung_bg/abschaltung{region}.asp"
UNPLANNED_URL = "https://www.elyug.bg/Customers/Unscheduled-power-cuts.aspx"
REGIONS = {
    "1": "Бургас",
    "2": "Кърджали",
    "3": "Пазарджик",
    "4": "Пловдив",
    "5": "Сливен",
    "6": "Смолян",
    "7": "Стара Загора",
    "8": "Хасково",
    "9": "Ямбол",
}
CELL_RE = re.compile(r"<td\b[^>]*>(.*?)</td>", re.S | re.I)
HOURS_RE = re.compile(r"(\d{1,2}[:.]\d{2})\s*[-–]\s*(\d{1,2}[:.]\d{2})")
DATE_RE = re.compile(r"\d{1,2}\.\d{1,2}\.\d{4}")
DATETIME_RE = re.compile(r"(\d{1,2}\.\d{1,2}\.\d{4})(?:\D{0,6}(\d{1,2})[:.](\d{2}))?")
INPUT_RE = re.compile(r"<input\b[^>]*>", re.I)
ATTR_RE = re.compile(r'(\w+)="([^"]*)"')
POSTBACK_RE = re.compile(
    r"href=\"javascript:__doPostBack\('([^']+)','([^']*)'\)\"[^>]*?title=\"([^\"]+)\"", re.I
)
UNPLANNED_LIST_ID = "BreakdownsList"


def _records(page: str) -> list[dict[str, str]]:
    """Label/value table rows grouped into records, each starting at 'Област'."""
    page = re.sub(r"<!--.*?-->", "", page, flags=re.S)
    records: list[dict[str, str]] = []
    for row in re.split(r"<tr\b", page, flags=re.I)[1:]:
        cells = CELL_RE.findall(row.split("</tr>", 1)[0])
        if len(cells) != 2:
            continue
        label, value = cells
        key = normalize(strip_tags(label)).rstrip(" :")
        if key == "ОБЛАСТ":
            records.append({})
        if records and key:
            records[-1][key] = strip_tags(value)
    return records


def _field(record: dict[str, str], prefix: str) -> str:
    return next((v for k, v in record.items() if k.startswith(prefix)), "")


def parse_planned(page: str, region: str) -> list[Outage]:
    outages: list[Outage] = []
    try:
        for record in _records(page):
            dates = DATE_RE.findall(_field(record, "ДАТА"))
            windows = HOURS_RE.findall(_field(record, "СРОК"))
            area = _field(record, "АДРЕС")
            if not dates or not windows or not area:
                raise ValueError(f"incomplete record {record!r}")
            first, last = parse_date(dates[0]), parse_date(dates[-1])
            outages += [
                Outage(REGIONS[region], "", area, start, end)
                for start, end in daily_windows(first, last, windows)
            ]
    except ValueError as err:
        raise OutageFormatError(f"planned outages not readable: {err}") from err
    return list(dict.fromkeys(outages))


def _time(value: str) -> datetime | None:
    """'13.11.2026 г.' (midnight) or '13.11.2026 г. 18:30'; None if there is no date."""
    if not (m := DATETIME_RE.search(value)):
        return None
    day = parse_date(m.group(1))
    hour, minute = (int(m.group(2)), int(m.group(3))) if m.group(2) else (0, 0)
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TIMEZONE)


def parse_unplanned(page: str, region: str) -> list[Outage]:
    start_at = page.find(UNPLANNED_LIST_ID)
    if start_at < 0:
        if "__doPostBack" in page:
            return []
        raise OutageFormatError("unplanned outage page not recognised")
    outages: list[Outage] = []
    try:
        for record in _records(page[start_at:]):
            area = _field(record, "ОПИСАНИЕ")
            start = _time(_field(record, "ДАТА"))
            if not area or start is None:
                raise ValueError(f"incomplete record {record!r}")
            end = _time(_field(record, "ОЧАКВАН"))
            outages.append(
                Outage(
                    REGIONS[region],
                    "",
                    area,
                    start,
                    end if end is not None and end > start else None,
                    KIND_UNPLANNED,
                )
            )
    except ValueError as err:
        raise OutageFormatError(f"unplanned outages not readable: {err}") from err
    return list(dict.fromkeys(outages))


def postback_form(page: str, region: str) -> dict[str, str]:
    """ASP.NET form fields that select the province's map area."""
    fields: dict[str, str] = {}
    for tag in INPUT_RE.findall(page):
        attrs = {k.lower(): html.unescape(v) for k, v in ATTR_RE.findall(tag)}
        if attrs.get("type", "").lower() == "hidden" and attrs.get("name"):
            fields[attrs["name"]] = attrs.get("value", "")
    wanted = normalize(REGIONS[region])
    for target, argument, title in POSTBACK_RE.findall(page):
        if normalize(html.unescape(title)) == wanted:
            return fields | {"__EVENTTARGET": target, "__EVENTARGUMENT": argument}
    raise OutageFormatError(f"province {REGIONS[region]} not found on the unplanned outage page")


class EvnClient(OperatorClient):
    name = "EVN"

    async def async_get_planned(self, region: str) -> list[Outage]:
        async def fetch() -> list[Outage]:
            body = await self._request(PLANNED_URL.format(region=region), f"planned {region}")
            return parse_planned(body.decode("cp1251", "replace"), region)

        return await self._cached(f"planned|{region}", fetch)

    async def async_get_unplanned(self, region: str) -> list[Outage]:
        async def fetch() -> list[Outage]:
            page = await self._request(UNPLANNED_URL, "unplanned page")
            form = postback_form(page.decode("utf-8", "replace"), region)
            body = await self._request(UNPLANNED_URL, f"unplanned {region}", data=form)
            return parse_unplanned(body.decode("utf-8", "replace"), region)

        return await self._cached(f"unplanned|{region}", fetch)


class PlaceSource(OutageSource):
    """Planned and unplanned outages of a province whose description mentions the place."""

    has_current = True

    def __init__(self, client: EvnClient, region: str, place: str, text: str) -> None:
        if region not in REGIONS:
            raise OutageError(f"unknown EVN province {region}")
        self._client = client
        self._region = region
        self._place = place
        self._text = text

    def _match(self, outages: list[Outage]) -> list[Outage]:
        return [o for o in outages if o.matches(self._place, text=self._text)]

    async def async_current(self) -> list[Outage]:
        return self._match(await self._client.async_get_unplanned(self._region))

    async def async_planned(self) -> list[Outage]:
        return self._match(await self._client.async_get_planned(self._region))
