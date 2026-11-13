"""The supported distribution operators."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..api import OperatorClient
from ..const import OPERATOR_ERM_ZAPAD, OPERATOR_ERP_SEVER, OPERATOR_EVN
from . import erm_zapad, erp_sever, evn


@dataclass(frozen=True, slots=True)
class Operator:
    key: str
    # Company name as shown in Bulgaria; used as device manufacturer and in the attribution.
    name: str
    client_class: type[OperatorClient]
    # Page with the outage information, linked from the device and the calendar events.
    url: str
    # Provinces to choose from (id -> name); empty if the operator needs none.
    regions: dict[str, str] = field(default_factory=dict)


OPERATORS: dict[str, Operator] = {
    OPERATOR_ERM_ZAPAD: Operator(
        OPERATOR_ERM_ZAPAD, "ЕРМ Запад", erm_zapad.ErmZapadClient, erm_zapad.PLAN_URL
    ),
    OPERATOR_ERP_SEVER: Operator(
        OPERATOR_ERP_SEVER,
        "Електроразпределение Север",
        erp_sever.ErpSeverClient,
        erp_sever.PAGE_URL,
        erp_sever.REGIONS,
    ),
    OPERATOR_EVN: Operator(
        OPERATOR_EVN, "Електроразпределение Юг", evn.EvnClient, evn.PAGE_URL, evn.REGIONS
    ),
}
