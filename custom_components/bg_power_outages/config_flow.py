"""Config flow: one entry per client number or per monitored place of one operator."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import OutageError, OutageRateLimited, normalize
from .const import (
    CONF_ADDRESS,
    CONF_CLIENT_NUMBER,
    CONF_DISTRICT,
    CONF_OPERATOR,
    CONF_PLACE,
    CONF_REGION,
    CONF_TEXT,
    DOMAIN,
    OPERATOR_ERM_ZAPAD,
    OPERATOR_ERP_SEVER,
    OPERATOR_EVN,
)
from .coordinator import create_source, get_client
from .operators import OPERATORS
from .operators.erm_zapad import CLIENT_NUMBER_RE, ErmZapadClient, mask_client_number

ERM_PLACE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PLACE): str,
        vol.Optional(CONF_DISTRICT, default=""): str,
    }
)
CLIENT_SCHEMA = vol.Schema({vol.Required(CONF_CLIENT_NUMBER): str})


def _region_schema(operator: str) -> vol.Schema:
    options = [
        SelectOptionDict(value=key, label=name) for key, name in OPERATORS[operator].regions.items()
    ]
    return vol.Schema(
        {
            vol.Required(CONF_REGION): SelectSelector(
                SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)
            ),
            vol.Required(CONF_PLACE): str,
            vol.Optional(CONF_TEXT, default=""): str,
        }
    )


def _schema(data: Mapping[str, Any]) -> vol.Schema:
    if CONF_CLIENT_NUMBER in data:
        return CLIENT_SCHEMA
    if data[CONF_OPERATOR] == OPERATOR_ERM_ZAPAD:
        return ERM_PLACE_SCHEMA
    return _region_schema(data[CONF_OPERATOR])


def _place_title(place: str, extra: str) -> str:
    return f"{place.title()} ({extra.title()})" if extra else place.title()


def _client_title(address: str, client_number: str) -> str:
    """The number is masked: the title becomes the device name and so part of entity IDs."""
    masked = mask_client_number(client_number)
    return f"{address.title()} ({masked})" if address else masked


def _unique_id(data: Mapping[str, Any]) -> str:
    operator = data[CONF_OPERATOR]
    if CONF_CLIENT_NUMBER in data:
        return f"{operator}|client|{data[CONF_CLIENT_NUMBER]}"
    if operator == OPERATOR_ERM_ZAPAD:
        return f"{operator}|{data[CONF_DISTRICT]}|{data[CONF_PLACE]}"
    return f"{operator}|{data[CONF_REGION]}|{data[CONF_PLACE]}|{data[CONF_TEXT]}"


def _title(data: Mapping[str, Any]) -> str:
    if CONF_CLIENT_NUMBER in data:
        return _client_title(data.get(CONF_ADDRESS, ""), data[CONF_CLIENT_NUMBER])
    if data[CONF_OPERATOR] == OPERATOR_ERM_ZAPAD:
        return _place_title(data.get(CONF_PLACE, ""), data.get(CONF_DISTRICT, ""))
    return _place_title(data.get(CONF_PLACE, ""), data.get(CONF_TEXT, ""))


class OutageConfigFlow(ConfigFlow, domain=DOMAIN):
    """Operator first; then, for ЕРМ Запад, by client number or by place, else by place."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="user", menu_options=[OPERATOR_ERM_ZAPAD, OPERATOR_EVN, OPERATOR_ERP_SEVER]
        )

    async def async_step_erm_zapad(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(step_id=OPERATOR_ERM_ZAPAD, menu_options=["client", "place"])

    async def async_step_client(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_step_target("client", OPERATOR_ERM_ZAPAD, True, user_input)

    async def async_step_place(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_step_target("place", OPERATOR_ERM_ZAPAD, False, user_input)

    async def async_step_evn(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_step_target(OPERATOR_EVN, OPERATOR_EVN, False, user_input)

    async def async_step_erp_sever(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_step_target(
            OPERATOR_ERP_SEVER, OPERATOR_ERP_SEVER, False, user_input
        )

    async def _async_step_target(
        self, step_id: str, operator: str, client: bool, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if (
            user_input is not None
            and (data := await self._async_validate(operator, client, user_input, errors))
            is not None
        ):
            await self.async_set_unique_id(_unique_id(data))
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=_title(data), data=data)
        schema = _schema({CONF_OPERATOR: operator} | ({CONF_CLIENT_NUMBER: ""} if client else {}))
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    async def _async_validate(
        self, operator: str, client: bool, user_input: dict[str, Any], errors: dict[str, str]
    ) -> dict[str, Any] | None:
        """Entry data, or None with errors set; the operator's site is asked once."""
        if client:
            return await self._async_validate_client(user_input, errors)
        place = normalize(user_input.get(CONF_PLACE, ""))
        if not place:
            errors[CONF_PLACE] = "invalid_place"
            return None
        data: dict[str, Any] = {CONF_OPERATOR: operator, CONF_PLACE: place}
        if operator == OPERATOR_ERM_ZAPAD:
            data[CONF_DISTRICT] = normalize(user_input.get(CONF_DISTRICT, ""))
        else:
            if user_input.get(CONF_REGION) not in OPERATORS[operator].regions:
                errors[CONF_REGION] = "invalid_region"
                return None
            data[CONF_REGION] = user_input[CONF_REGION]
            data[CONF_TEXT] = normalize(user_input.get(CONF_TEXT, ""))
        try:
            await create_source(self.hass, data).async_planned()
        except OutageRateLimited:
            errors["base"] = "rate_limited"
        except OutageError:
            errors["base"] = "cannot_connect"
        return None if errors else data

    async def _async_validate_client(
        self, user_input: dict[str, Any], errors: dict[str, str]
    ) -> dict[str, Any] | None:
        number = "".join(user_input.get(CONF_CLIENT_NUMBER, "").split())
        if not CLIENT_NUMBER_RE.match(number):
            errors[CONF_CLIENT_NUMBER] = "invalid_client_number"
            return None
        client = cast(ErmZapadClient, get_client(self.hass, OPERATOR_ERM_ZAPAD))
        try:
            points = await client.async_get_points(number)
        except OutageRateLimited:
            errors["base"] = "rate_limited"
            return None
        except OutageError:
            errors["base"] = "cannot_connect"
            return None
        if not points:
            errors[CONF_CLIENT_NUMBER] = "unknown_client_number"
            return None
        addresses = list(dict.fromkeys(p.address for p in points if p.address))
        return {
            CONF_OPERATOR: OPERATOR_ERM_ZAPAD,
            CONF_CLIENT_NUMBER: number,
            CONF_ADDRESS: ", ".join(addresses),
        }

    # --- reconfigure (same operator and kind as the entry) -----------------------------------

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        operator = entry.data[CONF_OPERATOR]
        client = CONF_CLIENT_NUMBER in entry.data
        errors: dict[str, str] = {}
        if (
            user_input is not None
            and (data := await self._async_validate(operator, client, user_input, errors))
            is not None
        ):
            unique_id = _unique_id(data)
            if any(
                e.unique_id == unique_id and e.entry_id != entry.entry_id
                for e in self._async_current_entries(include_ignore=False)
            ):
                return self.async_abort(reason="already_configured")
            # A title the user has changed is kept.
            title = _title(data) if entry.title == _title(entry.data) else entry.title
            return self.async_update_reload_and_abort(
                entry, unique_id=unique_id, title=title, data=data
            )
        schema = _schema(entry.data)
        suggested = user_input or {k: v for k, v in entry.data.items() if k in schema.schema}
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
            description_placeholders={"operator": OPERATORS[operator].name},
        )
