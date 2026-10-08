from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
import json
from pathlib import Path
from typing import Any

from .live_game_service import LiveGameService
from .live_season_save import (
    DEFAULT_RESOLVER_CONTRACT,
)
from .repository import DataRepository
from .save_slots import (
    SAVE_KIND_AUTOSAVE,
    SAVE_KIND_MANUAL,
)


def _json_default(value: Any):
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(
        f"not JSON serializable: "
        f"{type(value).__name__}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "KokoSimNew live game save/service CLI"
        )
    )
    parser.add_argument(
        "--data-dir",
        default="data",
    )
    parser.add_argument(
        "--save-root",
        default="out/saves",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=2026,
    )
    parser.add_argument(
        "--resolver-contract",
        default=DEFAULT_RESOLVER_CONTRACT,
    )
    parser.add_argument(
        "--max-backups",
        type=int,
        default=3,
    )

    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    new = commands.add_parser(
        "new",
        help="create a new live season",
    )
    new.add_argument("slot_id")
    new.add_argument(
        "--seed",
        type=int,
        required=True,
    )
    new.add_argument("--start-date")
    new.add_argument("--title")

    commands.add_parser(
        "list",
        help="list save slots",
    )

    status = commands.add_parser(
        "status",
        help="inspect a save without restoring runtime",
    )
    status.add_argument("slot_id")
    status.add_argument(
        "--source",
        default="latest",
    )

    recoveries = commands.add_parser(
        "recoveries",
        help="list primary and backup recovery sources",
    )
    recoveries.add_argument("slot_id")

    rename = commands.add_parser(
        "rename",
        help="change user-facing slot title",
    )
    rename.add_argument("slot_id")
    rename.add_argument("title")

    manual_save = commands.add_parser(
        "save",
        help="load a source and write a manual save",
    )
    manual_save.add_argument("slot_id")
    manual_save.add_argument(
        "--source",
        default="latest",
    )

    recover = commands.add_parser(
        "recover",
        help="promote a recovery source to primary",
    )
    recover.add_argument("slot_id")
    recover.add_argument(
        "--source",
        required=True,
    )
    recover.add_argument(
        "--kind",
        choices=[
            SAVE_KIND_MANUAL,
            SAVE_KIND_AUTOSAVE,
        ],
        default=SAVE_KIND_MANUAL,
    )

    for name in (
        "play-today",
        "next-day",
    ):
        action = commands.add_parser(name)
        action.add_argument("slot_id")
        action.add_argument(
            "--no-autosave",
            action="store_true",
        )

    advance_to = commands.add_parser(
        "advance-to",
    )
    advance_to.add_argument("slot_id")
    advance_to.add_argument("date")
    advance_to.add_argument(
        "--no-autosave",
        action="store_true",
    )

    advance_through = commands.add_parser(
        "advance-through",
    )
    advance_through.add_argument(
        "slot_id"
    )
    advance_through.add_argument("date")
    advance_through.add_argument(
        "--no-autosave",
        action="store_true",
    )

    delete = commands.add_parser(
        "delete",
        help="delete an entire slot",
    )
    delete.add_argument("slot_id")
    delete.add_argument(
        "--confirm",
        action="store_true",
        help="required to actually delete",
    )

    return parser


def run_command(
    args: argparse.Namespace,
    service: LiveGameService,
) -> dict:
    command = args.command

    if command == "new":
        session = service.new_game(
            args.slot_id,
            rng_seed=args.seed,
            start_date=args.start_date,
            title=args.title,
        )
        return {
            "command": command,
            "session": session.summary(),
            "slot": (
                service.slots.slot_summary(
                    args.slot_id
                ).to_dict()
            ),
        }

    if command == "list":
        return {
            "command": command,
            "slots": service.list_games(),
        }

    if command == "status":
        return {
            "command": command,
            "save": service.slots.inspect(
                args.slot_id,
                source=args.source,
            ),
            "slot_metadata": (
                service.slots
                .read_user_metadata(
                    args.slot_id
                ).to_dict()
                if (
                    service.slots
                    .read_user_metadata(
                        args.slot_id
                    )
                    is not None
                )
                else None
            ),
        }

    if command == "recoveries":
        return {
            "command": command,
            "slot_id": args.slot_id,
            "sources": (
                service.recovery_sources(
                    args.slot_id
                )
            ),
        }

    if command == "rename":
        return {
            "command": command,
            "metadata": (
                service.rename_game(
                    args.slot_id,
                    args.title,
                )
            ),
        }

    if command == "save":
        session = service.load_game(
            args.slot_id,
            source=args.source,
        )
        saved = service.save_game(
            session,
            kind=SAVE_KIND_MANUAL,
        )
        return {
            "command": command,
            "saved": saved,
        }

    if command == "recover":
        session = service.recover_game(
            args.slot_id,
            source=args.source,
            promote_kind=args.kind,
        )
        return {
            "command": command,
            "slot_id": args.slot_id,
            "source": args.source,
            "promote_kind": args.kind,
            "current_date": (
                session.state.current_date
                .isoformat()
            ),
        }

    if command == "play-today":
        session = service.load_game(
            args.slot_id
        )
        return service.play_today(
            session,
            autosave=not args.no_autosave,
        )

    if command == "next-day":
        session = service.load_game(
            args.slot_id
        )
        return service.next_day(
            session,
            autosave=not args.no_autosave,
        )

    if command == "advance-to":
        session = service.load_game(
            args.slot_id
        )
        return service.advance_to(
            session,
            args.date,
            autosave=not args.no_autosave,
        )

    if command == "advance-through":
        session = service.load_game(
            args.slot_id
        )
        return service.advance_through(
            session,
            args.date,
            autosave=not args.no_autosave,
        )

    if command == "delete":
        if not args.confirm:
            raise ValueError(
                "delete requires --confirm"
            )
        service.delete_game(
            args.slot_id
        )
        return {
            "command": command,
            "slot_id": args.slot_id,
            "deleted": True,
        }

    raise ValueError(
        f"unknown command: {command}"
    )


def main(
    argv: list[str] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    data_dir = Path(args.data_dir)
    repo = DataRepository(data_dir)
    service = LiveGameService(
        repo,
        data_dir,
        save_root=args.save_root,
        year=args.year,
        resolver_contract=(
            args.resolver_contract
        ),
        max_backups=args.max_backups,
    )
    payload = run_command(
        args,
        service,
    )
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            default=_json_default,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
