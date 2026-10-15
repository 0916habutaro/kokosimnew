"""Stage108 synthetic registration: reviewed 32 entrants, immutable 33 schools.

The official labels were checked in Stage103. Their order is NOT a draw order.
20/team and alternate-position 10+10 are game assumptions, not official rules.
"""
from dataclasses import asdict, dataclass
from pathlib import Path

from game_core.players import PlayerRosterGenerator, POSITION_SLOTS
from .repository import DataRepository
from .joint_team_registration_lab import RegisteredPlayer, RegisteredTeam, _sha, _identical

YEAR, COMPETITION = 2026, 'CMP000041'
ROSTER_SEED, ABILITY_SEED, SELECTION_SEED = 430103, 430103, 430108
VERSION = 'stage43g108_yamanashi_registration_v1'
PREFIX = f'LAB108:{YEAR}:{COMPETITION}:'
SELECTION = 'synthetic_alternate_position20_seed430108_v1'
# (official displayed label, local school-ID reconciliation); Stage103 table.
OFFICIAL = (
    ('上野原', (222,)), ('山梨農林・塩山', (202,220)), ('富士学苑', (225,)),
    ('山梨学院', (216,)), ('北杜', (197,)), ('吉田', (226,)), ('富士北稜', (227,)),
    ('富士河口湖', (228,)), ('山梨', (219,)), ('巨摩', (204,)), ('日川', (218,)),
    ('甲府南', (207,)), ('甲府城西', (210,)), ('甲府工', (213,)), ('甲府昭和', (201,)),
    ('甲府東', (215,)), ('甲府一', (214,)), ('甲府西', (209,)), ('白根', (203,)),
    ('笛吹', (217,)), ('身延', (206,)), ('都留興譲館', (224,)), ('都留', (221,)),
    ('青洲', (205,)), ('韮崎工', (199,)), ('韮崎', (198,)), ('帝京三', (196,)),
    ('日大明誠', (223,)), ('日本航空', (200,)), ('東海大甲府', (211,)),
    ('甲府商', (208,)), ('駿台甲府', (212,)),
)
SCHOOLS = tuple(f'SCH{n:06d}' for n in range(196,229))


@dataclass(frozen=True)
class AnnualRegistration:
    version: str
    year: int
    competition_id: str
    roster_seed: int
    ability_seed: int
    selection_seed: int
    roster_set_sha256: str
    school_fingerprints: tuple[tuple[str, str], ...]
    teams: tuple[RegisteredTeam, ...]

    def to_dict(self):
        return asdict(self)


def registration_from_rosters(repo, rosters):
    if type(rosters) is not tuple or tuple(r.school_id for r in rosters) != SCHOOLS:
        raise ValueError('exact ordered 33 school authorities required')
    generator = PlayerRosterGenerator()
    for roster in rosters:
        expected = generator.generate_for_school_id(repo, roster.school_id, YEAR, ROSTER_SEED)
        if not _identical(roster.to_dict(), expected.to_dict()):
            raise ValueError('school authority provenance/scalar types differ')
    fingerprints = tuple((r.school_id, _sha(r.to_dict())) for r in rosters)
    fp, people = dict(fingerprints), {r.school_id: r.players for r in rosters}
    if len({p.player_id for r in rosters for p in r.players}) != 660:
        raise ValueError('660 distinct permanent IDs required')
    teams = []
    for label, numbers in OFFICIAL:
        schools = tuple(f'SCH{n:06d}' for n in numbers)
        tid = PREFIX + ('joint' if len(schools) == 2 else schools[0])
        if tid in repo.schools or any(s not in repo.schools for s in schools):
            raise ValueError('unknown school or team namespace collision')
        selected, used = [], set()
        for index, position in enumerate(POSITION_SLOTS):
            sid = schools[(index + SELECTION_SEED) % len(schools)]
            candidates = sorted((p for p in people[sid] if p.primary_position == position
                                 and p.player_id not in used), key=lambda p: p.roster_no)
            if not candidates:
                raise ValueError('synthetic selection cannot fill position')
            p = candidates[0]; used.add(p.player_id)
            selected.append(RegisteredPlayer(YEAR, COMPETITION, tid, p.player_id,
                sid, index+1, fp[sid], p))
        teams.append(RegisteredTeam(YEAR, COMPETITION, tid, label, VERSION, SELECTION,
                                    schools, tuple(selected)))
    membership = [s for t in teams for s in t.school_ids]
    registered = [p.player_id for t in teams for p in t.players]
    if sorted(membership) != list(SCHOOLS) or len(set(registered)) != 640:
        raise ValueError('missing/duplicate schools or registered IDs')
    return AnnualRegistration(VERSION, YEAR, COMPETITION, ROSTER_SEED, ABILITY_SEED,
        SELECTION_SEED, _sha(tuple(r.to_dict() for r in rosters)), fingerprints, tuple(teams))


def validate_registration(reg, repo, rosters):
    if not _identical(reg, registration_from_rosters(repo, rosters)):
        raise ValueError('Stage108 exact immutable registration required')


def fixed_authorities():
    repo = DataRepository(Path(__file__).resolve().parents[1] / 'data')
    rosters = tuple(PlayerRosterGenerator().generate_for_school_id(repo, s, YEAR, ROSTER_SEED)
                    for s in SCHOOLS)
    return repo, rosters, registration_from_rosters(repo, rosters)
