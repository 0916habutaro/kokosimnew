from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

from .historical_match_archive import HistoricalMatchArchive
from .year_transition import require_year_end, year_end_readiness
from .live_season_planner import (
    LiveSeasonGraphPlanner,
)
from .live_season_save import (
    DEFAULT_RESOLVER_CONTRACT,
    plan_fingerprint,
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
        session = LiveGameSession(
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
        # Repair a crash between the JSON save and archive commit.
        # Older backup loads never delete matches written by newer saves.
        self._sync_history(session)
        return session

    def _history_archive(self, slot_id: str) -> HistoricalMatchArchive:
        return HistoricalMatchArchive(
            self.slots.slot_dir(slot_id) / "historical_matches.sqlite3"
        )

    def _sync_history(self, session: LiveGameSession) -> dict:
        completed = (
            match.__dict__
            for scheduled in session.state.competitions.values()
            for match in scheduled.matches.values()
            if match.status == "completed"
        )
        return self._history_archive(session.slot_id).sync(
            year=session.state.year,
            rng_seed=session.state.rng_seed,
            resolver_contract=session.resolver_contract,
            plan_fingerprint=plan_fingerprint(session.plan),
            completed=completed,
        )

    def save_game(
        self,
        session: LiveGameSession,
        *,
        kind: str = SAVE_KIND_MANUAL,
    ) -> dict:
        # JSON first: if the archive operation fails or the process exits,
        # a later load deterministically replays and retries the archive.
        saved = self.slots.save(
            session.slot_id,
            session.plan,
            session.state,
            kind=kind,
            resolver_contract=session.resolver_contract,
        )
        return {**saved, "historical_archive": self._sync_history(session)}

    def autosave_game(self, session: LiveGameSession) -> dict:
        return self.save_game(session, kind=SAVE_KIND_AUTOSAVE)

    def year_end_status(self, session: LiveGameSession) -> dict:
        """Report blockers to sealing the finished year's match history."""
        return year_end_readiness(session.state)

    def finalize_season(self, session: LiveGameSession) -> dict:
        """Commit current-year history and seal it against later additions.

        Does not build or start the next season. The underlying live runtime
        is still restricted to its existing annual competition graph.
        """
        readiness = require_year_end(session.state)
        # The JSON save is the replayable checkpoint. Then the archive syncs
        # and checks an exact completed-match count before sealing.
        saved = self.save_game(session, kind=SAVE_KIND_MANUAL)
        sealed = self._history_archive(session.slot_id).seal_year(
            session.state.year,
            expected_match_count=readiness["completed_match_count"],
        )
        return {
            "action": "finalize_season",
            "year": session.state.year,
            "next_year": session.state.year + 1,
            "archive_sealed": True,
            "year_end_readiness": readiness,
            "save": saved,
            "archive": sealed,
            "next_year_gameplay_started": False,
        }

    def career_history_years(self, slot_id: str) -> list[dict]:
        return self._history_archive(slot_id).list_years()

    def historical_match(
        self, slot_id: str, year: int, competition_id: str, match_id: str
    ) -> dict | None:
        return self._history_archive(slot_id).get_match(
            year, competition_id, match_id
        )

    def historical_matches(
        self, slot_id: str, year: int, *, school_id: str = "",
        limit: int = 200, offset: int = 0,
    ) -> list[dict]:
        return self._history_archive(slot_id).list_matches(
            year, school_id=school_id, limit=limit, offset=offset,
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

    def _advance_with_checkpoints(
        self,
        session: LiveGameSession,
        target: str,
        *,
        autosave: bool | None,
        through: bool,
    ) -> dict:
        """Checkpoint completed match days during a long calendar jump.

        A single save at the end of a multi-day advance loses every game
        simulated since the previous save if the process stops mid-jump.
        Save the replayable JSON first and then sync the append-only history
        after each day that actually completed a match. Calendar-only days
        need no intermediate checkpoint. Explicit autosave=False retains
        the caller's manual-save contract.
        """
        enabled = (
            self.autosave_after_action
            if autosave is None
            else bool(autosave)
        )
        action = "advance_through" if through else "advance_to"
        if not enabled:
            result = (
                session.state.advance_through(target)
                if through else session.state.advance_to(target)
            )
            return {"action": action, **result, "autosave": None}

        target_date = (
            target if isinstance(target, date)
            else date.fromisoformat(target)
        )
        if target_date.year != session.state.year:
            raise ValueError("target_date must be inside season year")
        if target_date < session.state.current_date:
            raise ValueError("season runtime cannot move backward")

        advanced_days = 0
        played_match_count = 0
        last_save = None
        checkpoint_date = None
        while session.state.current_date < target_date:
            step = session.state.next_day()
            advanced_days += 1
            new_matches = int(step["played_match_count"])
            played_match_count += new_matches
            if new_matches:
                last_save = self.autosave_game(session)
                checkpoint_date = session.state.current_date

        result = {
            "current_date": session.state.current_date.isoformat(),
            "advanced_days": advanced_days,
            "played_match_count": played_match_count,
        }
        if through:
            # Include games on the target day in the final replayable save.
            result["played_match_count"] += len(session.state.play_today())
            result["processed_through"] = (
                session.state.current_date.isoformat()
            )

        if through or checkpoint_date != session.state.current_date:
            last_save = self.autosave_game(session)
        return {"action": action, **result, "autosave": last_save}

    def advance_to(
        self,
        session: LiveGameSession,
        target: str,
        *,
        autosave: bool | None = None,
    ) -> dict:
        return self._advance_with_checkpoints(
            session, target, autosave=autosave, through=False,
        )

    def advance_through(
        self,
        session: LiveGameSession,
        target: str,
        *,
        autosave: bool | None = None,
    ) -> dict:
        return self._advance_with_checkpoints(
            session, target, autosave=autosave, through=True,
        )

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
