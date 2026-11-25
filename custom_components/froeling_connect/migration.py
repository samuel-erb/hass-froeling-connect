"""Unique-ID migration for NXG entities.

Up to v0.1.x this integration built entity unique IDs from the API's per-value
UUID (``{facility_id}_{component_id}_{uuid}``). Those UUIDs are not stable:
with the controller update from v1.1.1 to v1.2.1, 14 of 25 boiler values got
new UUIDs, which made Home Assistant create duplicate entities (``..._2``) and
leave the old ones orphaned.

NXG params are now keyed by their ``name``. This module works out, without any
Home Assistant imports (so it can be unit tested), how to move the existing
registry entries onto the new IDs:

- An entity whose UUID still exists is mapped via that UUID.
- An entity whose UUID vanished is mapped via its original name (the API's
  ``displayText``), if that is unique within its component.
- If several entities map to the same new ID (old entity + duplicate created
  after the controller update), the oldest one is kept - it carries the
  history and the original entity_id - and the others are removed.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from .api import Param

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


@dataclass(frozen=True)
class RegistryItem:
    """The bits of an entity registry entry the migration needs."""

    entity_id: str
    unique_id: str
    original_name: str | None
    created_at: datetime | None = None

    @property
    def domain(self) -> str:
        return self.entity_id.split(".", 1)[0]


@dataclass(frozen=True)
class MigrationPlan:
    renames: dict[str, str]  # entity_id -> new unique_id
    removals: list[str]  # entity_ids of superseded duplicates


def unique_id_for(param: Param) -> str:
    return f"{param.facility_id}_{param.component_id}_{param.param_id}"


def plan_unique_id_migration(items: Iterable[RegistryItem], params: Iterable[Param]) -> MigrationPlan:
    items = list(items)
    by_prefix: dict[str, dict[str, dict[str, str]]] = {}
    current_ids: set[str] = set()
    text_counts: dict[tuple[str, str], int] = {}

    for param in params:
        prefix = f"{param.facility_id}_{param.component_id}_"
        maps = by_prefix.setdefault(prefix, {"source": {}, "text": {}})
        current_ids.add(unique_id_for(param))
        if param.source_id and param.source_id != param.param_id:
            maps["source"][param.source_id] = param.param_id
        if param.display_text:
            text_counts[(prefix, param.display_text)] = text_counts.get((prefix, param.display_text), 0) + 1
            maps["text"][param.display_text] = param.param_id
    for (prefix, text), count in text_counts.items():
        if count > 1:  # ambiguous, never guess
            by_prefix[prefix]["text"].pop(text, None)

    existing = {(item.domain, item.unique_id) for item in items}
    # (domain, target unique_id) -> [(item, matched via a UUID that still exists)]
    groups: dict[tuple[str, str], list[tuple[RegistryItem, bool]]] = {}

    for item in items:
        if item.unique_id in current_ids:
            continue
        prefix = max((p for p in by_prefix if item.unique_id.startswith(p)), key=len, default=None)
        if prefix is None:
            continue
        suffix = item.unique_id[len(prefix) :]
        if not _UUID_RE.match(suffix):
            continue
        maps = by_prefix[prefix]
        if suffix in maps["source"]:
            param_id, via_current_uuid = maps["source"][suffix], True
        elif item.original_name and item.original_name in maps["text"]:
            param_id, via_current_uuid = maps["text"][item.original_name], False
        else:
            continue
        groups.setdefault((item.domain, prefix + param_id), []).append((item, via_current_uuid))

    renames: dict[str, str] = {}
    removals: list[str] = []
    for (domain, target), candidates in groups.items():
        if (domain, target) in existing:
            # Already migrated earlier; leave leftovers alone rather than guess.
            continue
        # Oldest first. Without created_at, an entity matched via a vanished
        # UUID predates the one created for the new UUID.
        candidates.sort(
            key=lambda c: (
                c[0].created_at is None,
                c[0].created_at or datetime.min,
                c[1],
                c[0].entity_id,
            )
        )
        keeper, *duplicates = candidates
        renames[keeper[0].entity_id] = target
        removals.extend(item.entity_id for item, _ in duplicates)

    return MigrationPlan(renames=renames, removals=removals)
