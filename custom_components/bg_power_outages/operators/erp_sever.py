"""Електроразпределение Север (Energo-Pro, north-eastern Bulgaria).

Undocumented endpoint behind https://www.erpsever.bg/bg/prekysvanija (needs X-Requested-With):
  GET /bg/profil/xhr/?method=get_interruptions&region_id=<1-9>&type=all_active
    -> JSON [{"area_id": "<id>", "area_name": …, "total_location_result_rows_all_active": [
         {"id", "from": "16.11.2026", "to": "20.11.2026",
          "hours": {"array": [["9:00", "17:00"], …]}, "main": "Поради … в районите на:<br/><br/>
          гр. Варна - ул. …", "disturbance": "", "disturbance_hours": {"array": []}, …}, …]}]
All announced planned outages of the region in one answer ("offset" is ignored). A period with
hours means these hours on each day of the period. Unplanned outages and the check by client
number need a login (tok.erpsever.bg) and are not used.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..api import (
    KIND_PLANNED,
    KIND_POSSIBLE,
    OperatorClient,
    Outage,
    OutageFormatError,
    OutageSource,
    daily_windows,
    parse_date,
    strip_tags,
)

PAGE_URL = "https://www.erpsever.bg/bg/prekysvanija"
DATA_URL = (
    "https://www.erpsever.bg/bg/profil/xhr/?method=get_interruptions&region_id={region}"
    "&type=all_active&offset=0&archive_from_date=&archive_to_date="
)
REGIONS = {
    "1": "Варна",
    "2": "Велико Търново",
    "3": "Габрово",
    "4": "Добрич",
    "5": "Разград",
    "6": "Русе",
    "7": "Силистра",
    "8": "Търговище",
    "9": "Шумен",
}
ROWS_KEY = "total_location_result_rows_all_active"
AREA_SPLIT_RE = re.compile(r"<br\s*/?>\s*<br\s*/?>|районите на:", re.I)


def _area(text: str) -> tuple[str, str]:
    """'Поради … в районите на:<br/><br/>гр. Варна - …' -> (reason, affected area)."""
    parts = AREA_SPLIT_RE.split(text, maxsplit=1)
    reason, area = (parts[0], parts[1]) if len(parts) == 2 else ("", text)
    return strip_tags(reason), strip_tags(area).strip(" :")


def _windows(value: Any) -> list[tuple[str, str]]:
    items = value.get("array") if isinstance(value, dict) else None
    return [(str(w[0]), str(w[1])) for w in items or [] if isinstance(w, list) and len(w) == 2]


def _outages(row: dict[str, Any], region: str) -> list[Outage]:
    first, last = parse_date(str(row["from"])), parse_date(str(row["to"]))
    out = []
    reason, area = _area(str(row.get("main") or ""))
    kind = KIND_POSSIBLE if "възможни смущения" in reason.lower() else KIND_PLANNED
    if area:
        out += [
            Outage(region, "", area, start, end, kind)
            for start, end in daily_windows(first, last, _windows(row.get("hours")))
        ]
    _, disturbed = _area(str(row.get("disturbance") or ""))
    if disturbed:
        out += [
            Outage(region, "", disturbed, start, end, KIND_POSSIBLE)
            for start, end in daily_windows(first, last, _windows(row.get("disturbance_hours")))
        ]
    return out


def parse_interruptions(body: str, region: str) -> list[Outage]:
    try:
        data = json.loads(body.lstrip("\ufeff").strip())
        area = next(a for a in data if str(a.get("area_id")) == region)
        rows = area[ROWS_KEY]
        if not isinstance(rows, list):
            raise TypeError(f"{ROWS_KEY} is not a list")
        name = REGIONS.get(region, str(area.get("area_name", "")))
        outages = [o for row in rows for o in _outages(row, name)]
    except (ValueError, KeyError, TypeError, AttributeError, StopIteration) as err:
        raise OutageFormatError(f"unexpected outage list: {err!r}: {body[:200]!r}") from err
    return list(dict.fromkeys(outages))


class ErpSeverClient(OperatorClient):
    name = "ERP Sever"

    async def async_get_outages(self, region: str) -> list[Outage]:
        """All announced planned outages of a region."""

        async def fetch() -> list[Outage]:
            body = await self._request(
                DATA_URL.format(region=region),
                f"interruptions {region}",
                headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
            )
            return parse_interruptions(body.decode("utf-8", "replace"), region)

        return await self._cached(f"region|{region}", fetch)


class PlaceSource(OutageSource):
    """Planned outages of a region whose description mentions the place (and text)."""

    def __init__(self, client: ErpSeverClient, region: str, place: str, text: str) -> None:
        self._client = client
        self._region = region
        self._place = place
        self._text = text

    async def async_planned(self) -> list[Outage]:
        return [
            o
            for o in await self._client.async_get_outages(self._region)
            if o.matches(self._place, text=self._text)
        ]
