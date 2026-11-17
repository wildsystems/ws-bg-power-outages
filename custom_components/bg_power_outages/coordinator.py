"""Update coordinator: outages of one configured place or client number."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, cast

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_CLOSE
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.hass_dict import HassKey

from .api import (
    KIND_POSSIBLE,
    OperatorClient,
    Outage,
    OutageError,
    OutageFormatError,
    OutageRateLimited,
    OutageSource,
)
from .const import (
    CONF_ADDRESS,
    CONF_CLIENT_NUMBER,
    CONF_DISTRICT,
    CONF_OPERATOR,
    CONF_PLACE,
    CONF_REGION,
    CONF_TEXT,
    CURRENT_INTERVAL,
    DOMAIN,
    LOGGER,
    OPERATOR_ERM_ZAPAD,
    OPERATOR_ERP_SEVER,
    PLANNED_INTERVAL,
    STALE_AFTER,
    TIMEZONE,
)
from .operators import OPERATORS, erm_zapad, erp_sever, evn

type OutageConfigEntry = ConfigEntry[OutageCoordinator]

DATA_CLIENTS: HassKey[dict[str, OperatorClient]] = HassKey(DOMAIN)


def get_client(hass: HomeAssistant, operator: str) -> OperatorClient:
    """One client per operator and HA instance: shared downloads, one request at a time."""
    clients = hass.data.setdefault(DATA_CLIENTS, {})
    if (client := clients.get(operator)) is None:
        # The client outlives the entry that creates it, so the session must not be tied to that
        # entry (auto_cleanup would close it when the entry unloads): it is closed with HA.
        session = async_create_clientsession(
            hass, auto_cleanup=False, cookie_jar=aiohttp.DummyCookieJar()
        )

        @callback
        def _detach(_event: Event) -> None:
            session.detach()

        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_CLOSE, _detach)
        client = OPERATORS[operator].client_class(session, hass.async_add_executor_job)
        clients[operator] = client
    return client


def create_source(hass: HomeAssistant, data: dict[str, Any]) -> OutageSource:
    operator = data[CONF_OPERATOR]
    client = get_client(hass, operator)
    if operator == OPERATOR_ERM_ZAPAD:
        erm = cast(erm_zapad.ErmZapadClient, client)
        if CONF_CLIENT_NUMBER in data:
            number = data[CONF_CLIENT_NUMBER]
            address = data.get(CONF_ADDRESS) or erm_zapad.mask_client_number(number)
            return erm_zapad.ClientNumberSource(erm, number, address)
        return erm_zapad.PlaceSource(erm, data[CONF_PLACE], data.get(CONF_DISTRICT, ""))
    args = (data[CONF_REGION], data[CONF_PLACE], data.get(CONF_TEXT, ""))
    if operator == OPERATOR_ERP_SEVER:
        return erp_sever.PlaceSource(cast(erp_sever.ErpSeverClient, client), *args)
    return evn.PlaceSource(cast(evn.EvnClient, client), *args)


def format_issue_id(entry: ConfigEntry) -> str:
    return f"unrecognised_answer_{entry.entry_id}"


def update_failed(err: OutageError) -> UpdateFailed:
    """After a rate limit refusal the next refresh waits until requests are accepted again."""
    retry_after = err.retry_after if isinstance(err, OutageRateLimited) else None
    return UpdateFailed(str(err), retry_after=retry_after)


class OutageCoordinator(DataUpdateCoordinator[list[Outage]]):
    """Outages sorted by start, current ones included.

    Sources with current outages are checked every CURRENT_INTERVAL and their planned outages
    every PLANNED_INTERVAL; a failed planned check then keeps the previous planned outages.
    Sources with planned outages only are checked every PLANNED_INTERVAL.
    """

    config_entry: OutageConfigEntry

    def __init__(self, hass: HomeAssistant, entry: OutageConfigEntry) -> None:
        self.operator = OPERATORS[entry.data[CONF_OPERATOR]]
        self.source = create_source(hass, dict(entry.data))
        if CONF_CLIENT_NUMBER in entry.data:
            label = erm_zapad.mask_client_number(entry.data[CONF_CLIENT_NUMBER])
        else:
            label = entry.title
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {self.operator.key} {label}",
            update_interval=CURRENT_INTERVAL if self.source.has_current else PLANNED_INTERVAL,
        )
        # Planned outages absent from the previous successful update; empty after start-up.
        self.new_outages: list[Outage] = []
        self.current: list[Outage] = []
        self.planned: list[Outage] | None = None
        self._planned_at = 0.0
        self._planned_unrecognised = False
        self._last_success: float | None = None

    @property
    def data_fresh(self) -> bool:
        """Data exists and the last successful update is recent enough to show it."""
        return (
            self.data is not None
            and self._last_success is not None
            and time.monotonic() - self._last_success < STALE_AFTER.total_seconds()
        )

    def current_outages(self) -> list[Outage]:
        """Outages in progress: registered now, or planned with their time window lasting."""
        if self.source.current_includes_planned:
            return self.current
        now = datetime.now(TIMEZONE)
        seen = {(o.start, o.end) for o in self.current}
        return self.current + [
            o
            for o in self.planned or []
            if o.kind != KIND_POSSIBLE
            and o.start <= now
            and (o.end is None or now < o.end)
            and (o.start, o.end) not in seen
        ]

    async def _async_update_data(self) -> list[Outage]:
        self.new_outages = []
        outages = await self._async_fetch()
        self._last_success = time.monotonic()
        return outages

    def _planned_due(self) -> bool:
        # Half an update interval of slack: refreshes do not fire at exact intervals.
        due = (PLANNED_INTERVAL - CURRENT_INTERVAL / 2).total_seconds()
        return (
            not self.source.has_current
            or self.planned is None
            or time.monotonic() - self._planned_at >= due
        )

    async def _async_fetch(self) -> list[Outage]:
        current: list[Outage] = []
        if self.source.has_current:
            try:
                current = await self.source.async_current()
            except OutageFormatError as err:
                self._report_format_error(err)
                raise update_failed(err) from err
            except OutageError as err:
                raise update_failed(err) from err
        if self._planned_due():
            try:
                planned = await self.source.async_planned()
            except OutageFormatError as err:
                self._report_format_error(err)
                if not self.source.has_current:
                    raise update_failed(err) from err
                # Not understood: retrying soon would not help; show the current outage anyway.
                self._planned_unrecognised = True
                if self.planned is None:
                    self.planned = []
                self._planned_at = time.monotonic()
            except OutageError as err:
                if not self.source.has_current:
                    raise update_failed(err) from err
                LOGGER.warning("%s: planned outages not updated: %s", self.name, err)
            else:
                if self.planned is not None:
                    self.new_outages = [o for o in planned if o not in self.planned]
                self.planned, self._planned_at = planned, time.monotonic()
                self._planned_unrecognised = False
        if not self._planned_unrecognised:
            self._clear_format_error()
        self.current = current
        seen = {(o.start, o.end) for o in current}
        merged = current + [o for o in self.planned or [] if (o.start, o.end) not in seen]
        return sorted(dict.fromkeys(merged), key=lambda o: o.start)

    def _report_format_error(self, err: OutageFormatError) -> None:
        LOGGER.warning("%s: %s", self.name, err)
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            format_issue_id(self.config_entry),
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="unrecognised_answer",
            translation_placeholders={
                "operator": self.operator.name,
                "title": self.config_entry.title,
                "error": str(err),
            },
        )

    def _clear_format_error(self) -> None:
        ir.async_delete_issue(self.hass, DOMAIN, format_issue_id(self.config_entry))
