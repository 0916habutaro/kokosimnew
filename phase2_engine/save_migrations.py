from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Mapping


MigrationFunction = Callable[
    [dict[str, Any]],
    dict[str, Any],
]


class SaveMigrationError(ValueError):
    pass


@dataclass(frozen=True)
class SaveMigrationStep:
    from_version: str
    to_version: str
    migrate: MigrationFunction


class SaveMigrationRegistry:
    """Explicit linear migration registry for versioned save payloads."""

    def __init__(self):
        self._steps: dict[
            str,
            SaveMigrationStep,
        ] = {}

    def register(
        self,
        from_version: str,
        to_version: str,
        migrate: MigrationFunction,
    ) -> None:
        if not from_version or not to_version:
            raise ValueError(
                "migration versions are required"
            )
        if from_version == to_version:
            raise ValueError(
                "migration must change version"
            )
        if from_version in self._steps:
            raise ValueError(
                "migration already registered "
                f"for {from_version}"
            )
        self._steps[from_version] = (
            SaveMigrationStep(
                from_version=from_version,
                to_version=to_version,
                migrate=migrate,
            )
        )

    def registered_versions(
        self,
    ) -> list[str]:
        return sorted(self._steps)

    def path(
        self,
        from_version: str,
        to_version: str,
    ) -> list[SaveMigrationStep]:
        if from_version == to_version:
            return []
        if not from_version:
            raise SaveMigrationError(
                "save payload has no schema_version"
            )

        output = []
        current = from_version
        seen = set()
        while current != to_version:
            if current in seen:
                raise SaveMigrationError(
                    "save migration cycle detected"
                )
            seen.add(current)
            step = self._steps.get(current)
            if step is None:
                raise SaveMigrationError(
                    "no save migration path: "
                    f"{from_version} -> {to_version}; "
                    f"stopped at {current}"
                )
            output.append(step)
            current = step.to_version
        return output

    def migrate(
        self,
        payload: Mapping[str, Any],
        *,
        target_version: str,
    ) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise SaveMigrationError(
                "save payload must be an object"
            )
        data = deepcopy(dict(payload))
        source_version = str(
            data.get("schema_version") or ""
        )
        steps = self.path(
            source_version,
            target_version,
        )
        for step in steps:
            migrated = step.migrate(
                deepcopy(data)
            )
            if not isinstance(
                migrated,
                dict,
            ):
                raise SaveMigrationError(
                    "migration must return a dict: "
                    f"{step.from_version}"
                )
            if migrated.get(
                "schema_version"
            ) != step.to_version:
                raise SaveMigrationError(
                    "migration returned unexpected "
                    "schema_version: "
                    f"{step.from_version} -> "
                    f"{migrated.get('schema_version')}"
                )
            data = migrated
        return data


DEFAULT_SAVE_MIGRATION_REGISTRY = (
    SaveMigrationRegistry()
)
