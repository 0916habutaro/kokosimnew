from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
from typing import Literal

from .live_season_save import (
    DEFAULT_RESOLVER_CONTRACT,
    inspect_live_season_save,
    read_live_season_save,
    write_live_season_save,
)


SAVE_KIND_MANUAL = "manual"
SAVE_KIND_AUTOSAVE = "autosave"
SAVE_KINDS = {
    SAVE_KIND_MANUAL,
    SAVE_KIND_AUTOSAVE,
}

_SLOT_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
)


@dataclass(frozen=True)
class SaveSlotFile:
    slot_id: str
    source: str
    path: str
    exists: bool
    metadata: dict | None = None

    def to_dict(self) -> dict:
        return {
            "slot_id": self.slot_id,
            "source": self.source,
            "path": self.path,
            "exists": self.exists,
            "metadata": (
                dict(self.metadata)
                if self.metadata is not None
                else None
            ),
        }


@dataclass(frozen=True)
class SaveSlotSummary:
    slot_id: str
    manual: SaveSlotFile
    autosave: SaveSlotFile
    latest_source: str

    def to_dict(self) -> dict:
        return {
            "slot_id": self.slot_id,
            "manual": self.manual.to_dict(),
            "autosave": self.autosave.to_dict(),
            "latest_source": self.latest_source,
        }


class SaveSlotManager:
    """Manage manual/autosave files and rolling backups per slot."""

    def __init__(
        self,
        root_dir: str | Path,
        *,
        max_backups: int = 3,
    ):
        if max_backups < 0:
            raise ValueError(
                "max_backups must be >= 0"
            )
        self.root_dir = Path(root_dir)
        self.max_backups = max_backups

    @staticmethod
    def validate_slot_id(
        slot_id: str,
    ) -> str:
        value = str(slot_id).strip()
        if not _SLOT_RE.fullmatch(value):
            raise ValueError(
                "slot_id must match "
                "[A-Za-z0-9][A-Za-z0-9_-]{0,63}"
            )
        return value

    def slot_dir(
        self,
        slot_id: str,
    ) -> Path:
        value = self.validate_slot_id(
            slot_id
        )
        return self.root_dir / value

    def save_path(
        self,
        slot_id: str,
        kind: str,
    ) -> Path:
        if kind not in SAVE_KINDS:
            raise ValueError(
                f"unknown save kind: {kind}"
            )
        return (
            self.slot_dir(slot_id)
            / f"{kind}.json"
        )

    def backup_path(
        self,
        slot_id: str,
        kind: str,
        generation: int,
    ) -> Path:
        if kind not in SAVE_KINDS:
            raise ValueError(
                f"unknown save kind: {kind}"
            )
        if generation <= 0:
            raise ValueError(
                "backup generation must be >= 1"
            )
        return (
            self.slot_dir(slot_id)
            / "backups"
            / (
                f"{kind}."
                f"{generation:03d}.json"
            )
        )

    def _rotate_backups(
        self,
        slot_id: str,
        kind: str,
    ) -> None:
        if self.max_backups <= 0:
            return
        primary = self.save_path(
            slot_id,
            kind,
        )
        if not primary.exists():
            return

        backups = (
            self.slot_dir(slot_id)
            / "backups"
        )
        backups.mkdir(
            parents=True,
            exist_ok=True,
        )

        oldest = self.backup_path(
            slot_id,
            kind,
            self.max_backups,
        )
        if oldest.exists():
            oldest.unlink()

        for generation in range(
            self.max_backups - 1,
            0,
            -1,
        ):
            source = self.backup_path(
                slot_id,
                kind,
                generation,
            )
            if not source.exists():
                continue
            target = self.backup_path(
                slot_id,
                kind,
                generation + 1,
            )
            source.replace(target)

        first = self.backup_path(
            slot_id,
            kind,
            1,
        )
        temp = first.with_name(
            first.name + ".tmp"
        )
        shutil.copy2(primary, temp)
        temp.replace(first)

    def save(
        self,
        slot_id: str,
        plan,
        state,
        *,
        kind: str = SAVE_KIND_MANUAL,
        resolver_contract: str = (
            DEFAULT_RESOLVER_CONTRACT
        ),
    ) -> dict:
        self.validate_slot_id(slot_id)
        if kind not in SAVE_KINDS:
            raise ValueError(
                f"unknown save kind: {kind}"
            )
        target = self.save_path(
            slot_id,
            kind,
        )
        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self._rotate_backups(
            slot_id,
            kind,
        )
        payload = write_live_season_save(
            target,
            plan,
            state,
            resolver_contract=(
                resolver_contract
            ),
        )
        return {
            "slot_id": slot_id,
            "kind": kind,
            "path": str(target),
            "current_date": (
                payload["current_date"]
            ),
            "payload_checksum": (
                payload[
                    "payload_checksum"
                ]
            ),
            "backup_count": len(
                self.backup_files(
                    slot_id,
                    kind,
                )
            ),
        }

    def autosave(
        self,
        slot_id: str,
        plan,
        state,
        *,
        resolver_contract: str = (
            DEFAULT_RESOLVER_CONTRACT
        ),
    ) -> dict:
        return self.save(
            slot_id,
            plan,
            state,
            kind=SAVE_KIND_AUTOSAVE,
            resolver_contract=(
                resolver_contract
            ),
        )

    def backup_files(
        self,
        slot_id: str,
        kind: str,
    ) -> list[Path]:
        if kind not in SAVE_KINDS:
            raise ValueError(
                f"unknown save kind: {kind}"
            )
        return [
            path
            for generation in range(
                1,
                self.max_backups + 1,
            )
            if (
                path := self.backup_path(
                    slot_id,
                    kind,
                    generation,
                )
            ).exists()
        ]

    def _file_info(
        self,
        slot_id: str,
        source: str,
        path: Path,
    ) -> SaveSlotFile:
        if not path.exists():
            return SaveSlotFile(
                slot_id=slot_id,
                source=source,
                path=str(path),
                exists=False,
                metadata=None,
            )
        return SaveSlotFile(
            slot_id=slot_id,
            source=source,
            path=str(path),
            exists=True,
            metadata=inspect_live_season_save(
                path
            ),
        )

    @staticmethod
    def _latest_source(
        manual: SaveSlotFile,
        autosave: SaveSlotFile,
    ) -> str:
        candidates = [
            item
            for item in (
                manual,
                autosave,
            )
            if item.exists
            and item.metadata is not None
        ]
        if not candidates:
            return ""

        def key(item: SaveSlotFile):
            metadata = item.metadata or {}
            return (
                metadata.get(
                    "current_date",
                    "",
                ),
                int(
                    metadata.get(
                        "processed_date_count",
                        0,
                    )
                ),
                (
                    1
                    if item.source
                    == SAVE_KIND_AUTOSAVE
                    else 0
                ),
            )

        return max(
            candidates,
            key=key,
        ).source

    def slot_summary(
        self,
        slot_id: str,
    ) -> SaveSlotSummary:
        value = self.validate_slot_id(
            slot_id
        )
        manual = self._file_info(
            value,
            SAVE_KIND_MANUAL,
            self.save_path(
                value,
                SAVE_KIND_MANUAL,
            ),
        )
        autosave = self._file_info(
            value,
            SAVE_KIND_AUTOSAVE,
            self.save_path(
                value,
                SAVE_KIND_AUTOSAVE,
            ),
        )
        return SaveSlotSummary(
            slot_id=value,
            manual=manual,
            autosave=autosave,
            latest_source=self._latest_source(
                manual,
                autosave,
            ),
        )

    def list_slots(
        self,
    ) -> list[SaveSlotSummary]:
        if not self.root_dir.exists():
            return []
        output = []
        for path in sorted(
            self.root_dir.iterdir(),
            key=lambda value: value.name,
        ):
            if not path.is_dir():
                continue
            try:
                slot_id = (
                    self.validate_slot_id(
                        path.name
                    )
                )
            except ValueError:
                continue
            summary = self.slot_summary(
                slot_id
            )
            if (
                summary.manual.exists
                or summary.autosave.exists
            ):
                output.append(summary)
        return output

    def _source_path(
        self,
        slot_id: str,
        source: str,
    ) -> Path:
        value = self.validate_slot_id(
            slot_id
        )
        if source == "latest":
            summary = self.slot_summary(
                value
            )
            if not summary.latest_source:
                raise FileNotFoundError(
                    f"slot has no save: {value}"
                )
            source = (
                summary.latest_source
            )

        if source in SAVE_KINDS:
            path = self.save_path(
                value,
                source,
            )
        else:
            match = re.fullmatch(
                r"(manual|autosave)_backup_(\d+)",
                source,
            )
            if not match:
                raise ValueError(
                    f"unknown save source: {source}"
                )
            kind = match.group(1)
            generation = int(
                match.group(2)
            )
            path = self.backup_path(
                value,
                kind,
                generation,
            )

        if not path.exists():
            raise FileNotFoundError(
                f"save source not found: {path}"
            )
        return path

    def inspect(
        self,
        slot_id: str,
        *,
        source: str = "latest",
    ) -> dict:
        path = self._source_path(
            slot_id,
            source,
        )
        metadata = (
            inspect_live_season_save(
                path
            )
        )
        return {
            "slot_id": (
                self.validate_slot_id(
                    slot_id
                )
            ),
            "source": source,
            "path": str(path),
            **metadata,
        }

    def load(
        self,
        slot_id: str,
        planner,
        *,
        source: str = "latest",
        engine=None,
        resolver_contract: str = (
            DEFAULT_RESOLVER_CONTRACT
        ),
    ):
        path = self._source_path(
            slot_id,
            source,
        )
        return read_live_season_save(
            path,
            planner,
            engine=engine,
            resolver_contract=(
                resolver_contract
            ),
        )

    def delete_slot(
        self,
        slot_id: str,
    ) -> None:
        directory = self.slot_dir(
            slot_id
        )
        if directory.exists():
            shutil.rmtree(directory)
