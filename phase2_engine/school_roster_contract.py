"""County-independent, roster-only acceptance and streaming annual transitions.

No competition, calendar, match archive or product season-start authority.
A source receipt proves consistency within an owned trial, not authenticity.
"""
from dataclasses import dataclass
from typing import Protocol

from game_core.career_rosters import advance_school_roster
from game_core.players import PlayerRosterGenerator, validate_school_roster
from .career_roster_archive import _digest, _json

RECIPE = 'placeholder_v1/career_roster_v1/player_career_newcomer_v1'


@dataclass(frozen=True)
class RosterAcceptance:
    year: int
    career_seed: int
    recipe: str
    source_kind: str
    evidence: str
    # school ID, program ID, school name, prefecture, saved roster digest
    schools: tuple[tuple[str, str, str, str, str], ...]

    def to_dict(self):
        return dict(year=self.year, career_seed=self.career_seed, recipe=self.recipe,
                    source_kind=self.source_kind, evidence=self.evidence,
                    schools=self.schools, scope='roster-only trial',
                    season_start_authorized=False)


class RosterSource(Protocol):
    def snapshot(self):
        """Return saved school authorities and their source acceptance receipt."""
        ...


def accept_roster_source(rosters, repo, *, year, career_seed, evidence,
                         source_kind='roster_only_sandbox', recipe=RECIPE):
    """Validate a complete declared school set, independently of tournament gates.

    Verified tournament adapters supply their own evidence. This function never
    manufactures tournament completion or grants a product year-start token.
    """
    if (type(year) is not int or year < 1 or type(career_seed) is not int
            or recipe != RECIPE or type(evidence) is not str or not evidence
            or source_kind not in ('roster_only_sandbox', 'verified_saved_school_source')):
        raise ValueError('invalid roster source recipe/year/seed/evidence')
    schools, seen = [], set()
    for r in rosters:
        validate_school_roster(r)
        team = repo.team(r.school_id)
        if (type(r.reference_year) is not int or r.reference_year != year
                or type(r.rng_seed) is not int or r.rng_seed != career_seed
                or not team.program_id or not team.prefecture_code
                or (r.program_id, r.school_name) != (team.program_id, team.display_name)
                or any(p.generation_seed != career_seed or type(p.generation_seed) is not int
                       or p.name_source != 'placeholder_v1' for p in r.players)):
            raise ValueError('saved school/year/seed/name-provider differs')
        ids = {p.player_id for p in r.players}
        if seen & ids:
            raise ValueError('permanent ID belongs to multiple schools')
        seen.update(ids)
        schools.append((r.school_id, r.program_id, r.school_name, team.prefecture_code,
                        _digest(_json(r.to_dict()))))
    if not schools or len({s[0] for s in schools}) != len(schools):
        raise ValueError('empty or duplicate school source')
    return RosterAcceptance(year, career_seed, recipe, source_kind, evidence, tuple(sorted(schools)))


def stream_school_transitions(rosters, repo, acceptance, *, next_year, career_seed,
                              recipe=RECIPE):
    """One school/20 active players per transition; no historical match replay.

    Exhaust the stream before accepting the year. School order is canonical;
    a missing suffix cannot be mistaken for complete acceptance by the writer.
    """
    if (type(acceptance) is not RosterAcceptance or recipe != acceptance.recipe
            or recipe != RECIPE or type(next_year) is not int
            or next_year != acceptance.year + 1 or type(career_seed) is not int
            or career_seed != acceptance.career_seed):
        raise ValueError('adjacent year and original career recipe/seed required')
    seen, count = set(), 0
    for r in rosters:
        if count >= len(acceptance.schools):
            raise ValueError('extra source school')
        sid, program, name, pref, sha = acceptance.schools[count]
        team = repo.team(sid)
        if ((r.school_id, r.program_id, r.school_name) != (sid, program, name)
                or team.prefecture_code != pref or _digest(_json(r.to_dict())) != sha):
            raise ValueError('different saved school source')
        t = advance_school_roster(r, team, next_year=next_year, career_seed=career_seed,
                                  generator=PlayerRosterGenerator())
        ids = {p.player_id for p in (*r.players, *t.newcomers)}
        if seen & ids:
            raise ValueError('cross-school permanent ID collision')
        seen.update(ids)
        count += 1
        yield t
    if count != len(acceptance.schools):
        raise ValueError('partial source is not an accepted year')
