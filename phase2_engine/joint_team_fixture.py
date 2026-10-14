"""Stage103 read-only experiment; deliberately absent from game/replay writers.

A team is an annual competition entry, never a new school. The selection below
is a synthetic preview rule, not an official registration or simulation input.
"""
from dataclasses import dataclass
import hashlib
import json

from game_core.players import Player, PlayerRosterGenerator, POSITION_SLOTS, validate_school_roster

YEAR = 2026
COMPETITION = "CMP000041"
ROSTER_SEED = 430103
SCHOOLS = ("SCH000202", "SCH000220", "SCH000196", "SCH000197")
SOURCE = "stage43g103_self_generated_readonly_v1"
PREFIX = f"FX103:{YEAR}:{COMPETITION}:"


class JointTeamWriterUnsupported(ValueError):
    """The legacy engine/archive cannot represent mixed school membership."""


@dataclass(frozen=True)
class CompetitionTeamEntry:
    team_id: str
    label: str
    school_ids: tuple[str, ...]


ENTRIES = (
    CompetitionTeamEntry(PREFIX + "joint", "農林・塩山（自己生成検証）", SCHOOLS[:2]),
    CompetitionTeamEntry(PREFIX + "solo1", "帝京第三（自己生成検証）", (SCHOOLS[2],)),
    CompetitionTeamEntry(PREFIX + "solo2", "北杜（自己生成検証）", (SCHOOLS[3],)),
)


@dataclass(frozen=True)
class JointTeamFixture:
    entries: tuple[CompetitionTeamEntry, ...]
    # Frozen Player values detached from mutable SchoolRoster/cache containers.
    players: tuple[Player, ...]
    roster_sha256: str

    @classmethod
    def from_rosters(cls, repo, rosters, *, entries=ENTRIES):
        """Accept only the fixed built-in 2026 fixture, without acquiring a writer."""
        entries, rosters = tuple(entries), tuple(rosters)
        seen_schools, seen_teams = set(), set()
        for entry in entries:
            if (type(entry) is not CompetitionTeamEntry or type(entry.label) is not str or not entry.label
                    or type(entry.team_id) is not str
                    or type(entry.school_ids) is not tuple or not entry.school_ids
                    or not entry.team_id.startswith(PREFIX) or entry.team_id in repo.schools
                    or entry.team_id in seen_teams):
                raise ValueError("invalid fixture team namespace or membership")
            seen_teams.add(entry.team_id)
            for sid in entry.school_ids:
                if sid not in repo.schools or sid in seen_schools:
                    raise ValueError("unknown school or double competition entry")
                seen_schools.add(sid)
        if entries != ENTRIES or seen_schools != set(SCHOOLS):
            raise ValueError("only the reviewed small fixture is supported")
        if len(rosters) != len(SCHOOLS) or {r.school_id for r in rosters} != set(SCHOOLS):
            raise ValueError("missing or duplicate school authority")
        generator = PlayerRosterGenerator()
        players, payloads = [], []
        for roster in sorted(rosters, key=lambda r: r.school_id):
            validate_school_roster(roster)
            expected = generator.generate_for_school_id(repo, roster.school_id, YEAR, ROSTER_SEED)
            if roster.to_dict() != expected.to_dict():
                raise ValueError("school roster provenance changed")
            players.extend(roster.players)
            payloads.append(roster.to_dict())
        if len({p.player_id for p in players}) != len(players):
            raise ValueError("duplicate permanent player ID")
        raw = json.dumps(payloads, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return cls(entries, tuple(players), hashlib.sha256(raw.encode()).hexdigest())

    def preview(self, team_id):
        """20 slots: alternate schools per position slot, lowest unused roster_no.

        Original IDs, school, entry year and grade are retained. This does not
        manufacture abilities, scores, school wins or ranking history.
        """
        entry = next((e for e in self.entries if e.team_id == team_id), None)
        if entry is None:
            raise ValueError("team not in this historical fixture scope")
        selected, used = [], set()
        for index, position in enumerate(POSITION_SLOTS):
            sid = entry.school_ids[index % len(entry.school_ids)]
            candidates = sorted((p for p in self.players if p.school_id == sid
                and p.primary_position == position and p.player_id not in used),
                key=lambda p: p.roster_no)
            if not candidates:
                raise ValueError("fixture selection cannot fill a position")
            player = candidates[0]
            used.add(player.player_id)
            selected.append({"team_id": entry.team_id, "team_slot": index + 1,
                             **player.to_dict()})
        return {"source": SOURCE, "year": YEAR, "competition_id": COMPETITION,
                "team_id": entry.team_id, "label": entry.label,
                "school_ids": list(entry.school_ids), "selection_rule": "fixture_alternate_position20_v1",
                "roster_sha256": self.roster_sha256, "players": selected,
                "match_input_supported": False, "archived_results": None}

    def legacy_annual_input(self):
        raise JointTeamWriterUnsupported(
            "mixed-school team requires new engine, full-A and history contracts; writer refused")
