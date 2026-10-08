from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .live_season_planner import (
    LiveSeasonGraphPlanner,
)
from .live_season_save import (
    DEFAULT_RESOLVER_CONTRACT,
)
from .repository import DataRepository
from .save_slots import (
    SAVE_KIND_AUTOSAVE,
    SAVE_KIND_MANUAL,
    SaveSlotManager,
)


@dataclass
class LiveGameSession:
    slot_id: str
    plan: object
    state: object
    resolver_contract: str

    def summary(self) -> dict:
        return {
            "slot_id": self.slot_id,
            "resolver_contract": (
                self.resolver_contract
            ),
            "plan": self.plan.summary(),
            "runtime": self.state.summary(),
        }


class LiveGameService:
    """Facade used by future GUI/CLI for new/load/save and day progression."""

    def __init__(
        self,
        repo: DataRepository,
        data_dir: str | Path,
        *,
        save_root: str | Path = "out/saves",
        year: int = 2026,
        resolver_contract: str = (
            DEFAULT_RESOLVER_CONTRACT
        ),
        max_backups: int = 3,
        autosave_after_action: bool = True,
        planner_factory: (
            Callable[
                [
                    DataRepository,
                    Path,
                    int,
                    int,
                ],
                object,
            ]
            | None
        ) = None,
    ):
        if not resolver_contract:
            raise ValueError(
                "resolver_contract is required"
            )
        self.repo = repo
        self.data_dir = Path(data_dir)
        self.year = year
        self.resolver_contract = (
            resolver_contract
        )
        self.autosave_after_action = (
            autosave_after_action
        )
        self.planner_factory = (
            planner_factory
        )
        self.slots = SaveSlotManager(
            save_root,
            max_backups=max_backups,
        )

    def _planner(
        self,
        rng_seed: int,
        *,
        year: int | None = None,
    ):
        target_year = (
            self.year
            if year is None
            else int(year)
        )
        if self.planner_factory is not None:
            return self.planner_factory(
                self.repo,
                self.data_dir,
                int(rng_seed),
                target_year,
            )
        return LiveSeasonGraphPlanner(
            self.repo,
            self.data_dir,
            int(rng_seed),
            year=target_year,
        )

    def new_game(
        self,
        slot_id: str,
        *,
        rng_seed: int,
        start_date: str | None = None,
        title: str | None = None,
        engine=None,
        save_initial: bool = True,
    ) -> LiveGameSession:
        slot = (
            self.slots.validate_slot_id(
                slot_id
            )
        )
        planner = self._planner(
            rng_seed,
            year=self.year,
        )
        plan = planner.build_plan()
        state = plan.build_runtime(
            engine=engine,
            start_date=start_date,
        )
        session = LiveGameSession(
            slot_id=slot,
            plan=plan,
            state=state,
            resolver_contract=(
                self.resolver_contract
            ),
        )
        if title is not None:
            self.slots.write_user_metadata(
                slot,
                title=title,
            )
        if save_initial:
            self.save_game(
                session,
                kind=SAVE_KIND_MANUAL,
            )
        return session

    def load_game(
        self,
        slot_id: str,
        *,
        source: str = "latest",
        engine=None,
    ) -> LiveGameSession:
        metadata = self.slots.inspect(
            slot_id,
            source=source,
        )
        if metadata[
            "resolver_contract"
        ] != self.resolver_contract:
            raise ValueError(
                "save resolver contract differs "
                "from game service"
            )
        planner = self._planner(
            metadata["rng_seed"],
            year=metadata["year"],
        )
        plan, state = self.slots.load(
            slot_id,
            planner,
            source=source,
            engine=engine,
            resolver_contract=(
                self.resolver_contract
            ),
        )
        return LiveGameSession(
            slot_id=(
                self.slots.validate_slot_id(
                    slot_id
                )
            ),
            plan=plan,
            state=state,
            resolver_contract=(
                self.resolver_contract
            ),
        )

    def save_game(
        self,
        session: LiveGameSession,
        *,
        kind: str = SAVE_KIND_MANUAL,
    ) -> dict:
        return self.slots.save(
            session.slot_id,
            session.plan,
            session.state,
            kind=kind,
            resolver_contract=(
                session.resolver_contract
            ),
        )

    def autosave_game(
        self,
        session: LiveGameSession,
    ) -> dict:
        return self.slots.autosave(
            session.slot_id,
            session.plan,
            session.state,
            resolver_contract=(
                session.resolver_contract
            ),
        )

    def _maybe_autosave(
        self,
        session: LiveGameSession,
        enabled: bool | None,
    ) -> dict | None:
        should_save = (
            self.autosave_after_action
            if enabled is None
            else bool(enabled)
        )
        if not should_save:
            return None
        return self.autosave_game(
            session
        )

    def play_today(
        self,
        session: LiveGameSession,
        *,
        autosave: bool | None = None,
    ) -> dict:
        results = (
            session.state.play_today()
        )
        save = self._maybe_autosave(
            session,
            autosave,
        )
        return {
            "action": "play_today",
            "current_date": (
                session.state.current_date
                .isoformat()
            ),
            "played_match_count": len(
                results
            ),
            "results": results,
            "autosave": save,
        }

    def next_day(
        self,
        session: LiveGameSession,
        *,
        autosave: bool | None = None,
    ) -> dict:
        result = (
            session.state.next_day()
        )
        save = self._maybe_autosave(
            session,
            autosave,
        )
        return {
            "action": "next_day",
            **result,
            "autosave": save,
        }

    def advance_to(
        self,
        session: LiveGameSession,
        target: str,
        *,
        autosave: bool | None = None,
    ) -> dict:
        result = (
            session.state.advance_to(
                target
            )
        )
        save = self._maybe_autosave(
            session,
            autosave,
        )
        return {
            "action": "advance_to",
            **result,
            "autosave": save,
        }

    def advance_through(
        self,
        session: LiveGameSession,
        target: str,
        *,
        autosave: bool | None = None,
    ) -> dict:
        result = (
            session.state.advance_through(
                target
            )
        )
        save = self._maybe_autosave(
            session,
            autosave,
        )
        return {
            "action": "advance_through",
            **result,
            "autosave": save,
        }

    def list_games(self) -> list[dict]:
        return [
            summary.to_dict()
            for summary in self.slots.list_slots()
        ]

    def recovery_sources(
        self,
        slot_id: str,
    ) -> list[dict]:
        return self.slots.recovery_sources(
            slot_id
        )

    def rename_game(
        self,
        slot_id: str,
        title: str,
    ) -> dict:
        return (
            self.slots.rename_slot(
                slot_id,
                title,
            ).to_dict()
        )

    def recover_game(
        self,
        slot_id: str,
        *,
        source: str,
        promote_kind: str = SAVE_KIND_MANUAL,
        engine=None,
    ) -> LiveGameSession:
        session = self.load_game(
            slot_id,
            source=source,
            engine=engine,
        )
        self.save_game(
            session,
            kind=promote_kind,
        )
        return session

    def delete_game(
        self,
        slot_id: str,
    ) -> None:
        self.slots.delete_slot(
            slot_id
        )
