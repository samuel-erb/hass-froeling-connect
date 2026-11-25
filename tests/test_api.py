from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from custom_components.froeling_connect.api import (
    ComponentInfo,
    FacilityInfo,
    FroelingConnectClient,
    detect_version_from_components,
    extract_params,
    nxg_value_types_for,
    parse_version,
)
from custom_components.froeling_connect.const import NXG_VALUE_TYPES_V1_1, NXG_VALUE_TYPES_V1_2

from .fixtures import (
    BOILER_V111,
    HEATING_CIRCUIT_OVERVIEW_ITEMS,
    INFO_V121,
    MATERIAL_STORAGE_ITEMS,
    boiler_v121,
)

FID = 100001


def _by_name(params):
    return {p.name: p for p in params}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("v1.2.1", (1, 2, 1)),
        ("1.1.1", (1, 1, 1)),
        ("1_2_0", (1, 2, 0)),
        ("v1.3", (1, 3, 0)),
        ("", None),
        (None, None),
        ("unknown", None),
    ],
)
def test_parse_version(text, expected):
    assert parse_version(text) == expected


def test_value_types_per_version():
    assert nxg_value_types_for((1, 1, 1)) == NXG_VALUE_TYPES_V1_1
    assert nxg_value_types_for((1, 2, 1)) == NXG_VALUE_TYPES_V1_2
    assert nxg_value_types_for((1, 0, 9)) == NXG_VALUE_TYPES_V1_1  # older: oldest known profile
    assert nxg_value_types_for((1, 3, 0)) == NXG_VALUE_TYPES_V1_2  # newer: newest known profile
    assert nxg_value_types_for(None) == NXG_VALUE_TYPES_V1_2
    assert "TimestampValue" not in NXG_VALUE_TYPES_V1_1


def test_detect_version_from_components():
    def comp(raw):
        return ComponentInfo(FID, "50001", "Kessel", "Boiler", raw)

    assert detect_version_from_components([comp(BOILER_V111)]) == (1, 1, 1)
    assert detect_version_from_components([comp(boiler_v121())]) == (1, 2, 1)
    assert detect_version_from_components([comp({"usedTemplateVersion": "1_2_0"})]) == (1, 2, 0)
    assert detect_version_from_components([comp({})]) is None


def test_v111_params_keyed_by_name_and_deduplicated():
    params = extract_params(BOILER_V111, FID, "50001", value_types=nxg_value_types_for((1, 1, 1)))
    by_name = _by_name(params)
    assert [p.name for p in params].count("tempBoiler") == 1
    assert set(by_name) == {"componentName", "boilerType", "ignitionAvailable", "tempBoiler", "idFanIdFanSpeedSetpointEffective"}
    assert all(p.param_id == p.name for p in params)
    assert by_name["tempBoiler"].source_id == "00000000-0000-4000-8000-000000000005"
    assert by_name["tempBoiler"].kind == "numeric" and by_name["tempBoiler"].unit == "°C"
    assert by_name["boilerType"].options == {"-1": "Unbekannter Kesseltyp", "13": "S4 Turbo 15"}


def test_param_ids_stable_across_v111_to_v121():
    old = {p.param_id for p in extract_params(BOILER_V111, FID, "50001", value_types=nxg_value_types_for((1, 1, 1)))}
    new = {p.param_id for p in extract_params(boiler_v121(), FID, "50001", value_types=nxg_value_types_for((1, 2, 1)))}
    assert old <= new
    assert new - old == {"ignitionStartTimeIgnition", "ignitionIgnitionTimeSchedule"}


def test_v121_new_types():
    by_name = _by_name(extract_params(boiler_v121(), FID, "50001", value_types=nxg_value_types_for((1, 2, 1))))

    start = by_name["ignitionStartTimeIgnition"]
    assert start.kind == "timestamp"
    assert start.value == datetime(2026, 11, 24, 1, 0, tzinfo=timezone(timedelta(hours=1)))

    schedule = by_name["ignitionIgnitionTimeSchedule"]
    assert schedule.kind == "schedule"
    assert schedule.value == "Mo-So 05:00-18:00"
    assert len(schedule.attributes["time_frames"]) == 7


def test_v121_types_ignored_when_controller_reports_v111():
    names = {p.name for p in extract_params(boiler_v121(), FID, "50001", value_types=nxg_value_types_for((1, 1, 1)))}
    assert "ignitionStartTimeIgnition" not in names
    assert "ignitionIgnitionTimeSchedule" not in names
    assert "tempBoiler" in names


def test_string_and_point_of_time_values():
    by_name = _by_name(extract_params(HEATING_CIRCUIT_OVERVIEW_ITEMS, FID, "50002", value_types=NXG_VALUE_TYPES_V1_1))
    assert by_name["timeInformation"].kind == "text"
    assert by_name["timeInformation"].value == "23:00"
    assert by_name["timeInformation"].param_id == "timeInformation"  # has no "id" in the API
    point = by_name["timeInformationPointOfTime"]
    assert (point.kind, point.value, point.attributes) == ("text", "23:00", {"weekday": 3})


def test_invalid_number_is_none():
    (param,) = extract_params(MATERIAL_STORAGE_ITEMS, FID, "50003", value_types=NXG_VALUE_TYPES_V1_2)
    assert param.value is None


def test_schedule_groups_differing_days():
    raw = {
        "name": "s",
        "type": "TimeScheduleValue",
        "value": {
            "timeFrames": [
                {"startTime": {"hour": 6, "min": 0, "weekday": d}, "endTime": {"hour": 22, "min": 0, "weekday": d}}
                for d in range(5)
            ]
            + [
                {"startTime": {"hour": 8, "min": 30, "weekday": d}, "endTime": {"hour": 24, "min": 0, "weekday": d}}
                for d in (5, 6)
            ]
        },
    }
    (param,) = extract_params(raw, FID, "x", value_types=NXG_VALUE_TYPES_V1_2)
    assert param.value == "Mo-Fr 06:00-22:00; Sa-So 08:30-24:00"


def test_gen3200_mode_unchanged():
    legacy = {
        "topView": {
            "boilerTemp": {
                "parameterType": "NumValueObject",
                "id": "1_0_0_0_123",
                "name": "boilerTemp",
                "displayText": "Kesseltemperatur",
                "unit": "°C",
                "value": "65",
                "minVal": "0",
                "maxVal": "120",
            }
        }
    }
    (param,) = extract_params(legacy, FID, "1_100")
    assert (param.param_id, param.kind, param.value) == ("1_0_0_0_123", "numeric", "65")


def test_get_nxg_facility_status():
    client = FroelingConnectClient(session=None, username="u", password="p")  # type: ignore[arg-type]
    client._token = "t"
    client.user_id = 1
    requested = []

    async def fake_request(url, *, retry=True):
        requested.append(url)
        return INFO_V121

    client._request = fake_request  # type: ignore[method-assign]
    facility = FacilityInfo(FID, "S5 Dual", "GEN_NXG", {})
    status = asyncio.run(client.get_nxg_facility_status(facility))

    assert requested == [f"https://connect-api.froeling.com/fcs/v1.0/resources/user/1/nxg/facility/{FID}/info"]
    assert status.software_version == "v1.2.1"
    by_name = _by_name(status.params)
    assert by_name["softwareVersion"].value == "v1.2.1"
    assert by_name["connectionStatus"].value == "CONNECTED"
    assert by_name["lastUpdate"].kind == "timestamp"
    assert by_name["lastUpdate"].value.tzinfo is not None
