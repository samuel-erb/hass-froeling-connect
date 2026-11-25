"""Trimmed-down NXG payloads, shaped exactly like the live API responses.

Captured from an S5 Dual before (v1.1.1) and after (v1.2.1) a controller
software update; values shortened, no personal data.
"""

from __future__ import annotations

import copy

SVG_V111 = "https://connect-api.froeling.com/ctvps/v1.0/resources/service/new/svg?lang=de&generation=nxg&componentType=boiler&version=v1.1.1&tempBoiler=71%C2%B0C"
SVG_V121 = SVG_V111.replace("v1.1.1", "v1.2.1")


def _boiler_type(uuid: str) -> dict:
    return {
        "displayFullQualifiedText": "Kesseltyp",
        "displayText": "Kesseltyp",
        "editable": False,
        "id": uuid,
        "name": "boilerType",
        "possibleValues": [
            {"value": -1, "displayValue": "Unbekannter Kesseltyp", "iconId": "", "selectable": False},
            {"value": 13, "displayValue": "S4 Turbo 15", "iconId": "", "selectable": True},
        ],
        "type": "StringListValue",
        "value": 13,
    }


BOILER_V111 = {
    "allView": None,
    "componentId": "00000000-0000-4000-8000-000000000001",
    "componentIndex": 0,
    "componentType": "Boiler",
    "defaultName": "S5 Dual",
    "displayName": "",
    "displayType": "Boiler",
    "facilityGeneration": "GEN_NXG",
    "id": 50001,
    "svgUrl": SVG_V111,
    "topView": [
        {
            "displayText": "",
            "name": "generalView",
            "valueListEmpty": False,
            "valueItems": [
                {
                    "defaultValue": "S5 Dual",
                    "displayText": "Komponenten-Name",
                    "editable": True,
                    "id": "00000000-0000-4000-8000-000000000002",
                    "maxLength": 25,
                    "minLength": 0,
                    "name": "componentName",
                    "type": "TextValue",
                    "value": "",
                },
                _boiler_type("00000000-0000-4000-8000-000000000003"),
            ],
        },
        {
            "displayText": "",
            "name": "configView",
            "valueListEmpty": False,
            "valueItems": [
                {
                    "displayText": "Zündung vorhanden",
                    "editable": False,
                    "id": "00000000-0000-4000-8000-000000000004",
                    "name": "ignitionAvailable",
                    "type": "BooleanValue",
                    "value": True,
                },
            ],
        },
    ],
    "listView": [
        {
            "name": "stateView",
            "valueItems": [
                {
                    "decimal": 0,
                    "displayText": "Kesseltemperatur",
                    "displayUnit": "°C",
                    "editable": False,
                    "id": "00000000-0000-4000-8000-000000000005",
                    "name": "tempBoiler",
                    "type": "NumberValue",
                    "value": 71,
                },
                {
                    "displayText": "Saugzug Drehzahl",
                    "displayUnit": "%",
                    "editable": False,
                    "id": "00000000-0000-4000-8000-000000000006",
                    "name": "idFanIdFanSpeedSetpointEffective",
                    "type": "IntValue",
                    "value": 0,
                },
            ],
        }
    ],
    "valueItems": {
        # Same value again (same UUID) as in the views: must be deduplicated.
        "tempBoiler": {
            "displayText": "Kesseltemperatur",
            "displayUnit": "°C",
            "id": "00000000-0000-4000-8000-000000000005",
            "name": "tempBoiler",
            "type": "NumberValue",
            "value": 71,
        },
    },
    "additionalView": None,
}


def boiler_v121() -> dict:
    """v1.2.1: new UUIDs for some values, ignition settings with new value types."""
    boiler = copy.deepcopy(BOILER_V111)
    boiler["svgUrl"] = SVG_V121
    boiler["usedTemplateVersion"] = "1_2_0"
    general, config = boiler["topView"]
    general["valueItems"][0]["id"] = "00000000-0000-4000-8000-000000000007"  # componentName: new UUID
    config["valueItems"][0]["id"] = "00000000-0000-4000-8000-000000000008"  # ignitionAvailable: new UUID
    boiler["listView"][0]["valueItems"][1]["id"] = "00000000-0000-4000-8000-000000000009"  # idFan: new UUID
    config["valueItems"] += [
        {
            "displayText": "Startzeitpunkt Zünden",
            "editable": True,
            "id": "00000000-0000-4000-8000-000000000010",
            "name": "ignitionStartTimeIgnition",
            "type": "TimestampValue",
            "value": "2026-11-24T01:00:00+01:00",
        },
        {
            "displayText": "Zeitfenster Zündung",
            "editable": True,
            "id": "00000000-0000-4000-8000-000000000011",
            "name": "ignitionIgnitionTimeSchedule",
            "type": "TimeScheduleValue",
            "value": {
                "timeFrames": [
                    {
                        "startTime": {"hour": 5, "min": 0, "weekday": day},
                        "endTime": {"hour": 18, "min": 0, "weekday": day},
                    }
                    for day in (1, 2, 3, 4, 5, 6, 0)
                ]
            },
        },
    ]
    return boiler


HEATING_CIRCUIT_OVERVIEW_ITEMS = {
    "timeInformation": {
        "displayText": "Heizphase bis:",
        "displayValue": "23:00",
        "editable": False,
        "name": "timeInformation",
        "type": "StringValue",
        "value": "23:00",
    },
    "timeInformationPointOfTime": {
        "displayText": "Zeitstempel für Info Anzeige",
        "editable": False,
        "id": "00000000-0000-4000-8000-000000000012",
        "name": "timeInformationPointOfTime",
        "type": "PointOfTimeValue",
        "value": {"hour": 23, "min": 0, "weekday": 3},
    },
}

MATERIAL_STORAGE_ITEMS = {
    "fillMaterialStorage": {
        "displayText": "Lager befüllen",
        "displayUnit": "t",
        "id": "00000000-0000-4000-8000-000000000013",
        "isInvalid": True,
        "name": "fillMaterialStorage",
        "type": "NumberValue",
        "value": -1,
    }
}

INFO_V121 = {
    "errorItems": [],
    "valueItems": {
        "lastUpdate": {
            "displayText": "lastUpdate_text",
            "editable": False,
            "id": "lastUpdate",
            "name": "lastUpdate",
            "type": "TimestampValue",
            "value": "2026-11-25T15:50:56.270365021Z",
        },
        "connectionStatus": {
            "displayText": "connectionStatus_text",
            "displayValue": "CONNECTED",
            "editable": False,
            "id": "connectionStatus",
            "name": "connectionStatus",
            "type": "StringValue",
            "value": "CONNECTED",
        },
        "softwareVersion": {
            "displayText": "Software Version",
            "editable": False,
            "id": "00000000-0000-4000-8000-000000000014",
            "name": "softwareVersion",
            "type": "TextValue",
            "value": "v1.2.1",
        },
    },
}
