from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil

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
class SaveSlotMetadata:
    slot_id: str
    title: str
    created_at: str
    last_saved_at: str
    last_source: str
    year: int | None
    rng_seed: int | None
    current_date: str

    def to_dict(self) -> dict:
        return {
            "slot_id": self.slot_id,
            "title": self.title,
            "created_at": self.created_at,
            "last_saved_at": self.last_saved_at,
            "last_source": self.last_source,
            "year": self.year,
            "rng_seed": self.rng_seed,
            "current_date": self.current_date,
        }


@dataclass(frozen=True)
class SaveSlotFile:
    slot_id: str
    source: str
    path: str
    exists: bool
    metadata: dict | None = None
    status: str = "missing"
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "slot_id": self.slot_id,
            "source": self.source,
            "path": self.path,
            "exists": self.exists,
            "status": self.status,
            "error": self.error,
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
    user_metadata: SaveSlotMetadata | None = None

    def to_dict(self) -> dict:
        return {
            "slot_id": self.slot_id,
            "manual": self.manual.to_dict(),
            "autosave": self.autosave.to_dict(),
            "latest_source": self.latest_source,
            "user_metadata": (
                self.user_metadata.to_dict()
                if self.user_metadata is not None
                else None
            ),
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

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(
            timezone.utc
        ).replace(
            microsecond=0
        ).isoformat()

    def metadata_path(
        self,
        slot_id: str,
    ) -> Path:
        return (
            self.slot_dir(slot_id)
            / "slot_metadata.json"
        )

    def read_user_metadata(
        self,
        slot_id: str,
    ) -> SaveSlotMetadata | None:
        value = self.validate_slot_id(
            slot_id
        )
        path = self.metadata_path(value)
        if not path.exists():
            return None
        try:
            raw = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
        ):
            return None
        try:
            return SaveSlotMetadata(
                slot_id=value,
                title=str(
                    raw.get("title")
                    or value
                ),
                created_at=str(
                    raw.get("created_at")
                    or ""
                ),
                last_saved_at=str(
                    raw.get("last_saved_at")
                    or ""
                ),
                last_source=str(
                    raw.get("last_source")
                    or ""
                ),
                year=(
                    int(raw["year"])
                    if raw.get("year")
                    is not None
                    else None
                ),
                rng_seed=(
                    int(raw["rng_seed"])
                    if raw.get("rng_seed")
                    is not None
                    else None
                ),
                current_date=str(
                    raw.get("current_date")
                    or ""
                ),
            )
        except (
            TypeError,
            ValueError,
        ):
            return None

    def write_user_metadata(
        self,
        slot_id: str,
        *,
        title: str | None = None,
        save_metadata: dict | None = None,
        last_source: str = "",
    ) -> SaveSlotMetadata:
        value = self.validate_slot_id(
            slot_id
        )
        existing = self.read_user_metadata(
            value
        )
        now = self._now_iso()
        effective_title = (
            str(title).strip()
            if title is not None
            else (
                existing.title
                if existing is not None
                else value
            )
        )
        if not effective_title:
            effective_title = value

        metadata = SaveSlotMetadata(
            slot_id=value,
            title=effective_title,
            created_at=(
                existing.created_at
                if (
                    existing is not None
                    and existing.created_at
                )
                else now
            ),
            last_saved_at=(
                now
                if save_metadata is not None
                else (
                    existing.last_saved_at
                    if existing is not None
                    else ""
                )
            ),
            last_source=(
                last_source
                if save_metadata is not None
                else (
                    existing.last_source
                    if existing is not None
                    else ""
                )
            ),
            year=(
                int(
                    save_metadata["year"]
                )
                if (
                    save_metadata is not None
                    and save_metadata.get(
                        "year"
                    ) is not None
                )
                else (
                    existing.year
                    if existing is not None
                    else None
                )
            ),
            rng_seed=(
                int(
                    save_metadata["rng_seed"]
                )
                if (
                    save_metadata is not None
                    and save_metadata.get(
                        "rng_seed"
                    ) is not None
                )
                else (
                    existing.rng_seed
                    if existing is not None
                    else None
                )
            ),
            current_date=(
                str(
                    save_metadata.get(
                        "current_date"
                    )
                    or ""
                )
                if save_metadata is not None
                else (
                    existing.current_date
                    if existing is not None
                    else ""
                )
            ),
        )
        path = self.metadata_path(value)
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        temp = path.with_name(
            path.name + ".tmp"
        )
        temp.write_text(
            json.dumps(
                metadata.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temp.replace(path)
        return metadata

    def rename_slot(
        self,
        slot_id: str,
        title: str,
    ) -> SaveSlotMetadata:
        return self.write_user_metadata(
            slot_id,
            title=title,
        )

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
        user_metadata = self.write_user_metadata(
            slot_id,
            save_metadata=payload,
            last_source=kind,
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
            "user_metadata": (
                user_metadata.to_dict()
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
                status="missing",
                error="",
            )
        try:
            metadata = (
                inspect_live_season_save(
                    path
                )
            )
        except Exception as exc:
            return SaveSlotFile(
                slot_id=slot_id,
                source=source,
                path=str(path),
                exists=True,
                metadata=None,
                status="invalid",
                error=(
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
            )
        return SaveSlotFile(
            slot_id=slot_id,
            source=source,
            path=str(path),
            exists=True,
            metadata=metadata,
            status="valid",
            error="",
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
            user_metadata=(
                self.read_user_metadata(
                    value
                )
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

    def recovery_sources(
        self,
        slot_id: str,
    ) -> list[dict]:
        value = self.validate_slot_id(
            slot_id
        )
        candidates: list[
            tuple[str, Path]
        ] = [
            (
                SAVE_KIND_MANUAL,
                self.save_path(
                    value,
                    SAVE_KIND_MANUAL,
                ),
            ),
            (
                SAVE_KIND_AUTOSAVE,
                self.save_path(
                    value,
                    SAVE_KIND_AUTOSAVE,
                ),
            ),
        ]
        for kind in (
            SAVE_KIND_MANUAL,
            SAVE_KIND_AUTOSAVE,
        ):
            for generation in range(
                1,
                self.max_backups + 1,
            ):
                candidates.append((
                    (
                        f"{kind}_backup_"
                        f"{generation}"
                    ),
                    self.backup_path(
                        value,
                        kind,
                        generation,
                    ),
                ))

        output = []
        for source, path in candidates:
            if not path.exists():
                continue
            try:
                metadata = (
                    inspect_live_season_save(
                        path
                    )
                )
                output.append({
                    "source": source,
                    "path": str(path),
                    "status": "valid",
                    "error": "",
                    "metadata": metadata,
                })
            except Exception as exc:
                output.append({
                    "source": source,
                    "path": str(path),
                    "status": "invalid",
                    "error": (
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
                    "metadata": None,
                })
        return output

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
