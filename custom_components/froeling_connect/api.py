"""Thin wrapper around the (inofficial) Fröling Connect API.

Fröling has two, structurally very different, backend generations:

- "GEN_3200" (older Lambdatronic/Touchtronic controllers).
- "GEN_NXG" (current controller generation, e.g. S5/P5 series).

Neither is officially documented. Everything below (endpoints, request/response
shapes, auth flow) was reverse-engineered from the network traffic of
https://connect-web.froeling.com. This module has no dependency beyond
``aiohttp`` (bundled with Home Assistant) on purpose: the only published
PyPI package for this API ("froeling-connect") turned out to be an unrelated,
yanked package under the same name, not usable as a dependency.

Both generations ultimately expose "components" (boiler, heating circuit,
buffer tank, ...) that contain deeply nested "parameters" (a single sensor
value). Rather than hand-mapping every known parameter, we recursively walk
the raw JSON of a component and treat any dict that looks like a value
object (see ``_is_nxg_leaf``) as a parameter. This is deliberate: it is the only
way to surface *all* values, including ones added by future firmware/API
changes, without needing to reverse-engineer them first.

NXG is software-version aware: the controller's software version (e.g.
"v1.2.1") is read from the facility info endpoint, and only the value types
known for that version (``const.NXG_VERSION_PROFILES``) are turned into
params. NXG params are keyed by their ``name``: the API's per-value UUIDs
changed for many values with the update from v1.1.1 to v1.2.1.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from typing import Any

from aiohttp import ClientSession

from .const import (
    COMPONENT_REQUEST_DELAY_SECONDS,
    FACILITY_GENERATION_NXG,
    LEGACY_VALUE_TYPES,
    LOGIN_URL,
    LOGGER,
    NXG_ALL_VALUE_TYPES,
    NXG_COMPONENT_URL,
    NXG_INFO_URL,
    NXG_OVERVIEW_URL,
    NXG_VERSION_PROFILES,
    USER_FACILITY_URL,
)

LEGACY_COMPONENT_LIST_URL = (
    "https://connect-api.froeling.com/fcs/v1.0/resources/user/{user_id}/facility/{facility_id}/componentList"
)
LEGACY_COMPONENT_URL = (
    "https://connect-api.froeling.com/fcs/v1.0/resources/user/{user_id}/facility/{facility_id}/component/{component_id}"
)


class FroelingAuthError(Exception):
    """Raised when login fails or a session cannot be renewed."""


class FroelingApiError(Exception):
    """Raised for unexpected API responses."""


@dataclass(frozen=True)
class FacilityInfo:
    """A facility (heating system installation)."""

    facility_id: int
    name: str
    generation: str | None
    raw: dict


@dataclass(frozen=True)
class ComponentInfo:
    """A component (boiler, heating circuit, buffer tank, ...) of a facility."""

    facility_id: int
    component_id: str
    name: str
    model: str | None
    raw: dict


@dataclass(frozen=True)
class Param:
    """A single, normalized value read from a component."""

    facility_id: int
    component_id: str
    param_id: str
    name: str | None
    display_text: str | None
    kind: str  # "numeric" | "boolean" | "enum" | "text" | "timestamp" | "schedule"
    unit: str | None
    value: Any
    options: dict[str, str] | None = None
    attributes: dict[str, Any] | None = None
    # The API's own "id" of the value (a UUID for NXG). Not stable across
    # controller software updates (many changed with v1.2.x), hence not used as
    # param_id for NXG; kept only to migrate entities created by older versions
    # of this integration, which keyed on it.
    source_id: str | None = None


@dataclass(frozen=True)
class NxgFacilityStatus:
    """Result of the NXG facility info endpoint."""

    software_version: str | None
    params: list[Param]


# ---------------------------------------------------------------------------
# Software version handling
# ---------------------------------------------------------------------------

_VERSION_RE = re.compile(r"v?(\d+)[._](\d+)(?:[._](\d+))?")
_SVG_URL_VERSION_RE = re.compile(r"[?&]version=([^&]+)")
_reported_unverified_versions: set[tuple[int, int, int]] = set()


def parse_version(text: str | None) -> tuple[int, int, int] | None:
    """Parse "v1.2.1" / "1.2.1" / "1_2_0" into (1, 2, 1)."""
    if not text:
        return None
    match = _VERSION_RE.search(str(text))
    if not match:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch or 0)


def format_version(version: tuple[int, int, int] | None) -> str | None:
    return None if version is None else "v{}.{}.{}".format(*version)


def detect_version_from_components(components: list[ComponentInfo]) -> tuple[int, int, int] | None:
    """Fallback version detection when the info endpoint is unavailable.

    Every NXG component carries an ``svgUrl`` with a ``version=v1.2.1`` query
    parameter (seen on v1.1.1 and v1.2.1); v1.2.x additionally reports
    ``usedTemplateVersion`` (e.g. "1_2_0").
    """
    for component in components:
        match = _SVG_URL_VERSION_RE.search(component.raw.get("svgUrl") or "")
        if match and (version := parse_version(match.group(1))):
            return version
    for component in components:
        if version := parse_version(component.raw.get("usedTemplateVersion")):
            return version
    return None


def nxg_value_types_for(version: tuple[int, int, int] | None) -> frozenset[str]:
    """The NXG value types to read for a given controller software version."""
    if version is None:
        return NXG_ALL_VALUE_TYPES
    selected = NXG_VERSION_PROFILES[0][1]
    for min_version, value_types in NXG_VERSION_PROFILES:
        if version >= min_version:
            selected = value_types
    if version[:2] not in {min_version[:2] for min_version, _ in NXG_VERSION_PROFILES}:
        if version not in _reported_unverified_versions:
            _reported_unverified_versions.add(version)
            LOGGER.warning(
                "Fröling controller software %s has not been verified with this integration; "
                "reading it like the closest known version",
                format_version(version),
            )
    return selected


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

# GEN_3200 mode: kept exactly as before, this generation is not version aware.
_GEN3200_MODE_NXG_TYPES = frozenset({"NumberValue", "IntValue", "BooleanValue", "TextValue", "StringListValue"})
_WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")  # assumes weekday 0 = Monday (unverified)
_MAX_STATE_LENGTH = 255
_reported_unknown_types: set[str] = set()


def _is_legacy_leaf(node: dict) -> bool:
    return node.get("parameterType") in LEGACY_VALUE_TYPES


def _is_gen3200_mode_leaf(node: dict) -> bool:
    return _is_legacy_leaf(node) or node.get("type") in _GEN3200_MODE_NXG_TYPES


def _is_nxg_leaf(node: dict) -> bool:
    """Any NXG value object, known or not: "type" ends with "Value" and it has a "name"."""
    node_type = node.get("type")
    return isinstance(node_type, str) and node_type.endswith("Value") and "name" in node


def _walk(node: Any, is_leaf, path: tuple[str, ...] = ()) -> Iterator[tuple[dict, tuple[str, ...]]]:  # noqa: ANN001
    """Recursively find every parameter-shaped leaf dict in an API response."""
    if isinstance(node, dict):
        if is_leaf(node):
            yield node, path
            return
        for key, value in node.items():
            if key == "possibleValues":
                continue
            yield from _walk(value, is_leaf, (*path, key))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from _walk(item, is_leaf, (*path, str(index)))


def _normalize_legacy_leaf(raw: dict, base: dict) -> dict:
    param_type = raw["parameterType"]
    unit = raw.get("unit") or None
    value = raw.get("value")
    string_list = raw.get("stringListKeyValues")

    if param_type == "NumValueObject":
        if raw.get("minVal") == "0" and raw.get("maxVal") == "1" and not unit:
            return base | {"kind": "boolean", "unit": None, "value": value in ("1", 1, True)}
        return base | {"kind": "numeric", "unit": unit, "value": value}
    if string_list:
        return base | {"kind": "enum", "unit": unit, "value": str(value), "options": dict(string_list)}
    return base | {"kind": "text", "unit": unit, "value": value}


def _format_time(hour: Any, minute: Any) -> str:
    return f"{int(hour):02d}:{int(minute):02d}"


def _format_schedule(time_frames: list[dict]) -> str:
    """Compact summary like "Mo-So 05:00-18:00" of a TimeScheduleValue."""
    per_day: dict[int, list[str]] = {}
    for frame in time_frames:
        start, end = frame.get("startTime") or {}, frame.get("endTime") or {}
        try:
            weekday = int(start["weekday"])
            text = f"{_format_time(start['hour'], start['min'])}-{_format_time(end['hour'], end['min'])}"
        except (KeyError, TypeError, ValueError):
            continue
        per_day.setdefault(weekday, []).append(text)
    if not per_day:
        return "-"

    def day_name(day: int) -> str:
        return _WEEKDAYS[day] if 0 <= day < len(_WEEKDAYS) else str(day)

    # Group consecutive days with identical time frames.
    groups: list[tuple[int, int, str]] = []
    for day in sorted(per_day):
        frames = ", ".join(sorted(per_day[day]))
        if groups and groups[-1][1] == day - 1 and groups[-1][2] == frames:
            groups[-1] = (groups[-1][0], day, frames)
        else:
            groups.append((day, day, frames))
    parts = [
        f"{day_name(first)}{'' if first == last else '-' + day_name(last)} {frames}" for first, last, frames in groups
    ]
    summary = "; ".join(parts)
    return summary if len(summary) <= _MAX_STATE_LENGTH else summary[: _MAX_STATE_LENGTH - 1] + "…"


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        # Python < 3.11 cannot handle nanosecond fractions: cut to microseconds.
        trimmed = re.sub(r"(\.\d{6})\d+", r"\1", value.replace("Z", "+00:00"))
        try:
            parsed = datetime.fromisoformat(trimmed)
        except ValueError:
            return None
    return parsed if parsed.tzinfo else None


def _normalize_nxg_leaf(raw: dict, base: dict, value_types: frozenset[str]) -> dict | None:
    param_type = raw.get("type")
    if param_type not in value_types:
        if param_type not in _reported_unknown_types:
            _reported_unknown_types.add(param_type)
            LOGGER.debug("Ignoring NXG value type %s (e.g. %s)", param_type, raw.get("name"))
        return None

    unit = raw.get("displayUnit") or None
    value = raw.get("value")

    if param_type == "BooleanValue":
        return base | {"kind": "boolean", "unit": None, "value": bool(value)}
    if param_type in ("NumberValue", "IntValue"):
        if raw.get("isInvalid"):
            value = None
        return base | {"kind": "numeric", "unit": unit, "value": value}
    if param_type == "StringListValue":
        options = {str(pv["value"]): pv["displayValue"] for pv in raw.get("possibleValues", [])}
        return base | {"kind": "enum", "unit": unit, "value": str(value), "options": options}
    if param_type == "TextValue":
        return base | {"kind": "text", "unit": unit, "value": value}
    if param_type == "StringValue":
        return base | {"kind": "text", "unit": unit, "value": raw.get("displayValue") or value or None}
    if param_type == "PointOfTimeValue":
        if not isinstance(value, dict) or "hour" not in value:
            return base | {"kind": "text", "unit": None, "value": None}
        return base | {
            "kind": "text",
            "unit": None,
            "value": _format_time(value.get("hour", 0), value.get("min", 0)),
            "attributes": {"weekday": value.get("weekday")},
        }
    if param_type == "TimestampValue":
        return base | {"kind": "timestamp", "unit": None, "value": _parse_timestamp(value)}
    if param_type == "TimeScheduleValue":
        time_frames = (value.get("timeFrames") if isinstance(value, dict) else None) or []
        return base | {
            "kind": "schedule",
            "unit": None,
            "value": _format_schedule(time_frames),
            "attributes": {"time_frames": time_frames},
        }
    return None


def extract_params(
    raw_component: Any,
    facility_id: int,
    component_id: str,
    *,
    value_types: frozenset[str] | None = None,
) -> list[Param]:
    """Extract every parameter found anywhere in a component's raw JSON.

    ``value_types=None`` is the GEN_3200 mode (unchanged behaviour, params keyed
    by the API's id). Passing the NXG value types of the controller's software
    version (see ``nxg_value_types_for``) enables NXG mode: only those types are
    read and params are keyed by their ``name``, which - unlike the API's
    UUIDs - stays stable across controller software updates.
    """
    nxg_mode = value_types is not None
    is_leaf = _is_nxg_leaf if nxg_mode else _is_gen3200_mode_leaf
    params = []
    seen_ids: set[str] = set()
    for leaf, path in _walk(raw_component, is_leaf):
        name = leaf.get("name")
        source_id = leaf.get("id")
        if nxg_mode:
            param_id = name or source_id or ":".join(path)
        else:
            param_id = source_id or ":".join((*path, name or "value"))
        display_text = leaf.get("displayText") or leaf.get("displayName") or name
        base = {"param_id": param_id, "name": name, "display_text": display_text, "source_id": source_id}

        if param_id in seen_ids:
            continue
        if "parameterType" in leaf:
            kwargs = _normalize_legacy_leaf(leaf, base) if _is_legacy_leaf(leaf) else None
        else:
            kwargs = _normalize_nxg_leaf(leaf, base, value_types if nxg_mode else _GEN3200_MODE_NXG_TYPES)
        if kwargs is None:
            continue
        seen_ids.add(param_id)
        params.append(Param(facility_id=facility_id, component_id=component_id, **kwargs))
    return params


class FroelingConnectClient:
    """Fetches facilities, components and their parameters, generation-aware."""

    def __init__(self, session: ClientSession, username: str, password: str) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._token: str | None = None
        self.user_id: int | None = None

    async def login(self) -> None:
        """Authenticate and store the bearer token + user id."""
        async with self._session.post(
            LOGIN_URL,
            json={"osType": "web", "username": self._username, "password": self._password},
        ) as res:
            if res.status != HTTPStatus.OK:
                body = await res.text()
                raise FroelingAuthError(f"Login failed ({res.status}): {body}")
            token = res.headers.get("Authorization")
            body = await res.json()
        if not token:
            raise FroelingAuthError("Login response did not include an Authorization token.")
        self._token = token
        self.user_id = body["userData"]["userId"]

    async def _request(self, url: str, *, retry: bool = True) -> Any:
        if not self._token:
            await self.login()
        async with self._session.get(
            url, headers={"Authorization": self._token, "Accept": "application/json", "Accept-Language": "de"}
        ) as res:
            if res.status == HTTPStatus.UNAUTHORIZED and retry:
                LOGGER.debug("Token expired, re-authenticating")
                await self.login()
                return await self._request(url, retry=False)
            if res.status != HTTPStatus.OK:
                body = await res.text()
                raise FroelingApiError(f"GET {url} failed ({res.status}): {body}")
            return await res.json()

    async def get_facilities(self) -> list[FacilityInfo]:
        if not self._token:
            await self.login()
        listing = await self._request(USER_FACILITY_URL.format(user_id=self.user_id))
        return [
            FacilityInfo(
                facility_id=item["facilityId"],
                name=item.get("name") or str(item["facilityId"]),
                generation=item.get("facilityGeneration"),
                raw=item,
            )
            for item in listing
        ]

    def get_facility_info_params(
        self, facility: FacilityInfo, value_types: frozenset[str] | None = None
    ) -> list[Param]:
        """Facility-level values (operating hours, boiler type, ...) bundled with the facility listing."""
        if facility.generation == FACILITY_GENERATION_NXG:
            info = facility.raw.get("protocolNxgInfo") or {}
            return extract_params(
                info, facility.facility_id, "facility_info", value_types=value_types or NXG_ALL_VALUE_TYPES
            )
        info = facility.raw.get("protocol3200Info") or {}
        return extract_params(info, facility.facility_id, "facility_info")

    async def get_nxg_facility_status(self, facility: FacilityInfo) -> NxgFacilityStatus:
        """Software version + cloud-side facility info (connection status, last update, ...).

        Endpoint found on connect-web's "Info" page; returns
        ``{"valueItems": {"softwareVersion": {"type": "TextValue", "value": "v1.2.1"}, ...},
        "errorItems": [...]}``. This is cloud data, independent of the controller
        firmware, so all known value types are read.
        """
        body = await self._request(NXG_INFO_URL.format(user_id=self.user_id, facility_id=facility.facility_id))
        value_items = (body or {}).get("valueItems") or {}
        software_version = (value_items.get("softwareVersion") or {}).get("value") or None
        params = extract_params(value_items, facility.facility_id, "facility_info", value_types=NXG_ALL_VALUE_TYPES)
        return NxgFacilityStatus(software_version=software_version, params=params)

    async def get_components(self, facility: FacilityInfo) -> list[ComponentInfo]:
        if facility.generation == FACILITY_GENERATION_NXG:
            return await self._get_nxg_components(facility)
        return await self._get_legacy_components(facility)

    async def get_component_params(
        self, facility: FacilityInfo, component: ComponentInfo, value_types: frozenset[str] | None = None
    ) -> list[Param]:
        """Parameters of a component.

        For NXG pass the value types of the controller's software version
        (``nxg_value_types_for``); without them all known types are read.
        """
        if facility.generation == FACILITY_GENERATION_NXG:
            return extract_params(
                component.raw,
                facility.facility_id,
                component.component_id,
                value_types=value_types or NXG_ALL_VALUE_TYPES,
            )
        return extract_params(component.raw, facility.facility_id, component.component_id)

    async def _get_legacy_components(self, facility: FacilityInfo) -> list[ComponentInfo]:
        listing = await self._request(
            LEGACY_COMPONENT_LIST_URL.format(user_id=self.user_id, facility_id=facility.facility_id)
        )
        components = []
        for item in listing:
            component_id = item.get("componentId")
            if not component_id:
                continue
            await asyncio.sleep(COMPONENT_REQUEST_DELAY_SECONDS)
            try:
                detail = await self._request(
                    LEGACY_COMPONENT_URL.format(
                        user_id=self.user_id, facility_id=facility.facility_id, component_id=component_id
                    )
                )
            except FroelingApiError:
                LOGGER.exception("Failed to fetch legacy component %s", component_id)
                continue
            name = detail.get("displayName") or detail.get("standardName") or component_id
            model = detail.get("type")
            components.append(ComponentInfo(facility.facility_id, component_id, name, model, detail))
        return components

    async def _get_nxg_components(self, facility: FacilityInfo) -> list[ComponentInfo]:
        overview = await self._request(NXG_OVERVIEW_URL.format(user_id=self.user_id, facility_id=facility.facility_id))
        components = []
        for item in overview:
            numeric_id = item.get("componentId")
            if numeric_id is None:
                continue
            await asyncio.sleep(COMPONENT_REQUEST_DELAY_SECONDS)
            try:
                detail = await self._request(
                    NXG_COMPONENT_URL.format(
                        user_id=self.user_id, facility_id=facility.facility_id, component_id=numeric_id
                    )
                )
            except FroelingApiError:
                LOGGER.exception("Failed to fetch NXG component %s", numeric_id)
                continue
            name = detail.get("displayName") or detail.get("defaultName") or detail.get("displayType") or str(numeric_id)
            model = detail.get("displayType") or detail.get("componentType")
            components.append(ComponentInfo(facility.facility_id, str(numeric_id), name, model, detail))
        return components
