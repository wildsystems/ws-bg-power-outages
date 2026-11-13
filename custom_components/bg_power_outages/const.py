"""Constants for the Bulgaria power outages integration."""

import logging
from datetime import timedelta
from zoneinfo import ZoneInfo

DOMAIN = "bg_power_outages"
LOGGER = logging.getLogger(__package__)

CONF_OPERATOR = "operator"
CONF_PLACE = "place"
CONF_DISTRICT = "district"
CONF_REGION = "region"
CONF_TEXT = "text"
CONF_CLIENT_NUMBER = "client_number"
CONF_ADDRESS = "address"

OPERATOR_ERM_ZAPAD = "erm_zapad"
OPERATOR_ERP_SEVER = "erp_sever"
OPERATOR_EVN = "evn"

TIMEZONE = ZoneInfo("Europe/Sofia")

# Planned outages are published days ahead: refreshed every 3 hours.
PLANNED_INTERVAL = timedelta(hours=3)
# Outages registered right now (client number, or unplanned ones by place): every 30 minutes.
CURRENT_INTERVAL = timedelta(minutes=30)
# After a refusal for too many requests no request at all is sent to that operator for this long.
RATE_LIMIT_BACKOFF = timedelta(hours=1)
# Last good data stays available through failed refreshes for this long.
STALE_AFTER = timedelta(hours=12)
# Config entries refreshing within this window share one download.
CACHE_TTL = timedelta(minutes=10)
REQUEST_TIMEOUT = 40
PARSE_TIMEOUT = 60
# A published period ("from 16.11 to 20.11, 9:00-17:00") is expanded day by day up to this length.
MAX_PERIOD_DAYS = 31
