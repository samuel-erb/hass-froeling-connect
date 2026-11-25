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
# Facility info page: software/text version, connection status, last update, ...
NXG_INFO_URL = NXG_API_BASE + "/info"

# NXG leaf-value "type" fields, per controller software version.
#
# The set of value types the API returns depends on the software version
# installed on the boiler controller (reported by NXG_INFO_URL as
# "softwareVersion", e.g. "v1.2.1"). Each entry applies from its version
# upwards, until the next entry. Versions older than the first entry use the
# first entry; versions newer than the last one use the last one.
#
# - v1.1.x: verified against a live S5 Dual on v1.1.1.
# - v1.2.x: verified against the same S5 Dual after its update to v1.2.1. Adds
#   the ignition settings to the boiler ("TimestampValue" start time, a
#   "TimeScheduleValue" ignition window) and "usedTemplateVersion" to every
#   component.
NXG_VALUE_TYPES_V1_1 = frozenset(
    {
        "NumberValue",
        "IntValue",
        "BooleanValue",
        "TextValue",
        "StringListValue",
        "StringValue",
        "PointOfTimeValue",
    }
)
NXG_VALUE_TYPES_V1_2 = NXG_VALUE_TYPES_V1_1 | {"TimestampValue", "TimeScheduleValue"}

NXG_VERSION_PROFILES: tuple[tuple[tuple[int, int, int], frozenset[str]], ...] = (
    ((1, 1, 0), NXG_VALUE_TYPES_V1_1),
    ((1, 2, 0), NXG_VALUE_TYPES_V1_2),
)
# Every NXG value type this integration knows how to read. Used for the
# cloud-side info endpoint (not firmware dependent) and when the controller
# version cannot be determined.
NXG_ALL_VALUE_TYPES = NXG_VALUE_TYPES_V1_2

# Known legacy (GEN_3200) leaf-value "parameterType" fields.
LEGACY_VALUE_TYPES = {"NumValueObject", "StringValueObject"}
