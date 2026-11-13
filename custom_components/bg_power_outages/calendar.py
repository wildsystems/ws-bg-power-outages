"""Calendar of the outages (current one and the published or planned following ones)."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import KIND_POSSIBLE, KIND_UNPLANNED, Outage
from .const import LOGGER
from .coordinator import OutageConfigEntry, OutageCoordinator
from .entity import OutageEntity, now_local, pending
from .operators import Operator

PARALLEL_UPDATES = 0

# Shown for an outage without an expected restore time, extended as time passes.
UNKNOWN_END_SPAN = timedelta(hours=1)
# Published area descriptions can be long; the event title shows the beginning.
MAX_SUMMARY_PLACE = 60
SUMMARY = {
    KIND_UNPLANNED: "Непланирано прекъсване на тока",
    KIND_POSSIBLE: "Възможни смущения в захранването",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OutageConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([OutageCalendar(entry.runtime_data)])


def _end(outage: Outage) -> datetime:
    return outage.end or max(outage.start, now_local()) + UNKNOWN_END_SPAN


def _short(text: str) -> str:
    return text if len(text) <= MAX_SUMMARY_PLACE else text[: MAX_SUMMARY_PLACE - 1].rstrip() + "…"


def _event(outage: Outage, operator: Operator) -> CalendarEvent:
    kind = SUMMARY.get(outage.kind, "Планирано прекъсване на тока")
    if outage.point:
        description = f"Точка на измерване {outage.point}."
        if outage.end is None:
            description += " Очакваното време за възстановяване не е обявено."
        location = outage.place
    else:
        description = (
            f"{outage.place}\n\n"
            "Индикативно: засяга част от посоченото място, не непременно целия район. "
            f"Източник: {operator.name}, {operator.url}"
        )
        if outage.end is None:
            description += "\nОчакваното време за възстановяване не е обявено."
        location = ", ".join(
            part
            for part in (
                _short(outage.place),
                f"общ. {outage.district}" if outage.district else "",
                f"обл. {outage.oblast}" if outage.oblast else "",
            )
            if part
        )
    return CalendarEvent(
        start=outage.start,
        end=_end(outage),
        summary=f"{kind} – {_short(outage.place)}",
        description=description,
        location=location,
        uid="|".join(
            (
                outage.start.isoformat(),
                outage.end.isoformat() if outage.end else "",
                outage.point or outage.district,
                outage.place,
            )
        ),
    )


def _events(outages: list[Outage], operator: Operator) -> list[CalendarEvent]:
    """Events of the outages; one that HA rejects is skipped instead of failing the calendar."""
    events = []
    for outage in outages:
        try:
            events.append(_event(outage, operator))
        except HomeAssistantError as err:
            LOGGER.debug("outage at %s skipped in the calendar: %s", outage.start, err)
    return events


class OutageCalendar(OutageEntity, CalendarEntity):
    def __init__(self, coordinator: OutageCoordinator) -> None:
        super().__init__(coordinator, "planned_outages")

    @property
    def event(self) -> CalendarEvent | None:
        events = _events(pending(self.coordinator.data), self.coordinator.operator)
        return events[0] if events else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return _events(
            [o for o in self.coordinator.data if o.start < end_date and _end(o) > start_date],
            self.coordinator.operator,
        )
