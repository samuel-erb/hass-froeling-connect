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
object (see ``_is_leaf``) as a parameter. This is deliberate: it is the only
way to surface *all* values, including ones added by future firmware/API
changes, without needing to reverse-engineer them first.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from aiohttp import ClientSession

from .const import (
    COMPONENT_REQUEST_DELAY_SECONDS,
    FACILITY_GENERATION_NXG,
    LEGACY_VALUE_TYPES,
    LOGIN_URL,
    LOGGER,
    NXG_COMPONENT_URL,
    NXG_OVERVIEW_URL,
    NXG_VALUE_TYPES,
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
    kind: str  # "numeric" | "boolean" | "enum" | "text"
    unit: str | None
    value: Any
    options: dict[str, str] | None = None


def _is_leaf(node: dict) -> bool:
    return ("parameterType" in node and node["parameterType"] in LEGACY_VALUE_TYPES) or (
        "type" in node and node["type"] in NXG_VALUE_TYPES
    )


def _walk(node: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[dict, tuple[str, ...]]]:
    """Recursively find every parameter-shaped leaf dict in an API response."""
    if isinstance(node, dict):
        if _is_leaf(node):
            yield node, path
            return
        for key, value in node.items():
            if key == "possibleValues":
                continue
            yield from _walk(value, (*path, key))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from _walk(item, (*path, str(index)))


def _normalize_leaf(raw: dict, path: tuple[str, ...]) -> dict | None:
    """Turn a raw leaf dict (legacy or NXG shape) into normalized Param kwargs."""
    name = raw.get("name")
    display_text = raw.get("displayText") or raw.get("displayName") or name
    param_id = raw.get("id") or ":".join((*path, name or "value"))
    base = {"param_id": param_id, "name": name, "display_text": display_text}

    if "parameterType" in raw:  # legacy GEN_3200 shape
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

    param_type = raw.get("type")  # NXG shape
    unit = raw.get("displayUnit") or None
    value = raw.get("value")

    if param_type == "BooleanValue":
        return base | {"kind": "boolean", "unit": None, "value": bool(value)}
    if param_type in ("NumberValue", "IntValue"):
        return base | {"kind": "numeric", "unit": unit, "value": value}
    if param_type == "StringListValue":
        options = {str(pv["value"]): pv["displayValue"] for pv in raw.get("possibleValues", [])}
        return base | {"kind": "enum", "unit": unit, "value": str(value), "options": options}
    if param_type == "TextValue":
        return base | {"kind": "text", "unit": unit, "value": value}
    return None


def extract_params(raw_component: dict, facility_id: int, component_id: str) -> list[Param]:
    """Extract every parameter found anywhere in a component's raw JSON."""
    params = []
    seen_ids: set[str] = set()
    for leaf, path in _walk(raw_component):
        kwargs = _normalize_leaf(leaf, path)
        if kwargs is None or kwargs["param_id"] in seen_ids:
            continue
        seen_ids.add(kwargs["param_id"])
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

    def get_facility_info_params(self, facility: FacilityInfo) -> list[Param]:
        """Facility-level values (operating hours, boiler type, ...) bundled with the facility listing."""
        info = facility.raw.get("protocolNxgInfo") or facility.raw.get("protocol3200Info") or {}
        return extract_params(info, facility.facility_id, "facility_info")

    async def get_components(self, facility: FacilityInfo) -> list[ComponentInfo]:
        if facility.generation == FACILITY_GENERATION_NXG:
            return await self._get_nxg_components(facility)
        return await self._get_legacy_components(facility)

    async def get_component_params(self, facility: FacilityInfo, component: ComponentInfo) -> list[Param]:
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
