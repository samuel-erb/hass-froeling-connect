"""Constants for the Fröling Connect integration."""

from __future__ import annotations

import logging

DOMAIN = "froeling_connect"
LOGGER = logging.getLogger(__package__)

ATTRIBUTION = "Data provided by Fröling Connect (inofficial API)"

CONF_FACILITY_ID = "facility_id"

FACILITY_GENERATION_NXG = "GEN_NXG"

DEFAULT_UPDATE_INTERVAL_SECONDS = 60

# Delay between per-component requests, to be gentle with the (undocumented,
# rate-limited) Fröling Connect API.
COMPONENT_REQUEST_DELAY_SECONDS = 0.5

LOGIN_URL = "https://connect-api.froeling.com/connect/v1.0/resources/login"
USER_FACILITY_URL = "https://connect-api.froeling.com/connect/v1.0/resources/service/user/{user_id}/facility"

NXG_API_BASE = "https://connect-api.froeling.com/fcs/v1.0/resources/user/{user_id}/nxg/facility/{facility_id}"
NXG_OVERVIEW_URL = NXG_API_BASE + "/web/overview"
NXG_COMPONENT_URL = NXG_API_BASE + "/web/component/{component_id}"

# Known NXG leaf-value "type" fields.
NXG_VALUE_TYPES = {"NumberValue", "IntValue", "BooleanValue", "TextValue", "StringListValue"}
# Known legacy (GEN_3200) leaf-value "parameterType" fields.
LEGACY_VALUE_TYPES = {"NumValueObject", "StringValueObject"}
