"""Stage43G-64: read-only selection of one explicitly named save slot.

Only direct non-symlink directories with an existing archive are candidates.
Selection constructs a *new* Stage43G-62 history bridge. The previous
year/school/match/player route stack never transfers between saved games.
"""
from __future__ import annotations

from pathlib import Path
import re

from .career_history_gui_bridge import CareerHistoryGuiBridge
from .career_cross_era_year_catalog import SOURCES

_SLOT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z")


class CareerHistorySlotConflict(ValueError):
    """A slot is unknown, outside the saves root, or cannot be read."""


class CareerHistorySlotSession:
    """Finite, bounded, per-slot read-only history session."""

    def __init__(self, saves_root: str | Path, slot_id: str, *,
                 year_page_size: int = 24):
        if type(year_page_size) is not int or not 1 <= year_page_size <= 24:
            raise CareerHistorySlotConflict("invalid saved year page size")
        self.saves_root = Path(saves_root)
        self.year_page_size = year_page_size
        self.slot_id: str | None = None
        self.bridge: CareerHistoryGuiBridge | None = None
        self.select(slot_id)

    def available_slots(self) -> list[str]:
        if not self.saves_root.is_dir() or self.saves_root.is_symlink():
            raise CareerHistorySlotConflict("saves root is not a directory")
        results = []
        for slot in self.saves_root.iterdir():
            if (slot.is_symlink() or not slot.is_dir()
                    or not _SLOT_ID.fullmatch(slot.name)
                    or ".." in slot.name):
                continue
            if any(
                (slot / name).is_file() and not (slot / name).is_symlink()
                for name, _, _, _ in SOURCES
            ):
                results.append(slot.name)
        return sorted(results)

    def select(self, slot_id: str) -> CareerHistoryGuiBridge:
        if (type(slot_id) is not str
                or not _SLOT_ID.fullmatch(slot_id)
                or ".." in slot_id):
            raise CareerHistorySlotConflict("invalid save slot identifier")
        if slot_id not in self.available_slots():
            raise CareerHistorySlotConflict("save slot not found")
        path = self.saves_root / slot_id
        if (path.is_symlink() or path.resolve().parent
                != self.saves_root.resolve()):
            raise CareerHistorySlotConflict("save slot escapes saves root")
        # Validate the new source and projection before replacing any active
        # bridge. Failure never destroys the old navigation/session.
        proposed = CareerHistoryGuiBridge(
            path, year_page_size=self.year_page_size,
        )
        if not proposed.page["data"]["years"]:
            raise CareerHistorySlotConflict("slot has no saved sealed years")
        self.bridge = proposed
        self.slot_id = slot_id
        return proposed
