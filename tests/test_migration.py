from __future__ import annotations

from datetime import datetime, timezone

from custom_components.froeling_connect.api import extract_params, nxg_value_types_for
from custom_components.froeling_connect.migration import RegistryItem, plan_unique_id_migration

from .fixtures import BOILER_V111, boiler_v121

FID = 100001
CID = "50001"
T0 = datetime(2026, 9, 15, tzinfo=timezone.utc)
T1 = datetime(2026, 11, 23, tzinfo=timezone.utc)


def _v121_params():
    return extract_params(boiler_v121(), FID, CID, value_types=nxg_value_types_for((1, 2, 1)))


def test_unchanged_uuid_is_renamed_to_name():
    items = [RegistryItem("sensor.s5_dual_kesseltemperatur", f"{FID}_{CID}_00000000-0000-4000-8000-000000000005", "Kesseltemperatur", T0)]
    plan = plan_unique_id_migration(items, _v121_params())
    assert plan.renames == {"sensor.s5_dual_kesseltemperatur": f"{FID}_{CID}_tempBoiler"}
    assert plan.removals == []


def test_changed_uuid_falls_back_to_name_and_removes_duplicate():
    items = [
        # created by v0.1.x on controller v1.1.1 (old UUID, now gone from the API)
        RegistryItem("binary_sensor.s5_dual_zundung_vorhanden", f"{FID}_{CID}_00000000-0000-4000-8000-000000000004", "Zündung vorhanden", T0),
        # duplicate created after the controller update to v1.2.1 (new UUID)
        RegistryItem("binary_sensor.s5_dual_zundung_vorhanden_2", f"{FID}_{CID}_00000000-0000-4000-8000-000000000008", "Zündung vorhanden", T1),
    ]
    plan = plan_unique_id_migration(items, _v121_params())
    assert plan.renames == {"binary_sensor.s5_dual_zundung_vorhanden": f"{FID}_{CID}_ignitionAvailable"}
    assert plan.removals == ["binary_sensor.s5_dual_zundung_vorhanden_2"]


def test_keeps_older_entity_without_created_at():
    items = [
        RegistryItem("sensor.new_2", f"{FID}_{CID}_00000000-0000-4000-8000-000000000009", "Saugzug Drehzahl"),
        RegistryItem("sensor.old", f"{FID}_{CID}_00000000-0000-4000-8000-000000000006", "Saugzug Drehzahl"),
    ]
    plan = plan_unique_id_migration(items, _v121_params())
    assert plan.renames == {"sensor.old": f"{FID}_{CID}_idFanIdFanSpeedSetpointEffective"}
    assert plan.removals == ["sensor.new_2"]


def test_already_migrated_and_foreign_ids_untouched():
    items = [
        RegistryItem("sensor.kessel", f"{FID}_{CID}_tempBoiler", "Kesseltemperatur", T0),
        RegistryItem("sensor.other_facility", f"999_{CID}_00000000-0000-4000-8000-000000000005", "Kesseltemperatur", T0),
        RegistryItem("sensor.unknown", f"{FID}_{CID}_00000000-0000-4000-8000-000000000015", "Gibt es nicht", T0),
    ]
    plan = plan_unique_id_migration(items, _v121_params())
    assert plan.renames == {}
    assert plan.removals == []


def test_stale_leftover_next_to_migrated_entity_is_left_alone():
    items = [
        RegistryItem("sensor.kessel", f"{FID}_{CID}_tempBoiler", "Kesseltemperatur", T1),
        RegistryItem("sensor.kessel_old", f"{FID}_{CID}_00000000-0000-4000-8000-000000000005", "Kesseltemperatur", T0),
    ]
    plan = plan_unique_id_migration(items, _v121_params())
    assert plan.renames == {} and plan.removals == []


def test_full_upgrade_scenario():
    """All entities created on v1.1.1, then duplicates for every changed UUID on v1.2.1."""
    old_params = extract_params(BOILER_V111, FID, CID, value_types=nxg_value_types_for((1, 1, 1)))
    new_params = _v121_params()
    domain = {"boolean": "binary_sensor"}
    items = [
        RegistryItem(f"{domain.get(p.kind, 'sensor')}.old_{p.name}", f"{FID}_{CID}_{p.source_id}", p.display_text, T0)
        for p in old_params
    ]
    old_uuids = {p.source_id for p in old_params}
    items += [
        RegistryItem(f"{domain.get(p.kind, 'sensor')}.new_{p.name}", f"{FID}_{CID}_{p.source_id}", p.display_text, T1)
        for p in new_params
        if p.source_id not in old_uuids
    ]
    plan = plan_unique_id_migration(items, new_params)

    expected = {f"{domain.get(p.kind, 'sensor')}.old_{p.name}": f"{FID}_{CID}_{p.name}" for p in old_params}
    # values that only exist since v1.2.1 move from their UUID to their name, too
    expected |= {
        f"sensor.new_{name}": f"{FID}_{CID}_{name}" for name in ("ignitionStartTimeIgnition", "ignitionIgnitionTimeSchedule")
    }
    assert plan.renames == expected
    # the duplicates created for the changed UUIDs are removed
    assert sorted(plan.removals) == sorted(
        ["sensor.new_componentName", "binary_sensor.new_ignitionAvailable", "sensor.new_idFanIdFanSpeedSetpointEffective"]
    )
    assert not set(plan.renames) & set(plan.removals)
