"""Self-generated inputs only; never read a user save."""
from pathlib import Path
from game_core.players import PlayerRosterGenerator
from phase2_engine.repository import DataRepository
from phase2_engine.joint_team_fixture import JointTeamFixture, SCHOOLS, YEAR, ROSTER_SEED
from phase2_engine.career_roster_archive import CareerRosterArchive

ROOT = Path(__file__).resolve().parents[1]


def fixture(slot=None):
    repo = DataRepository(ROOT / 'data')
    rosters = tuple(PlayerRosterGenerator().generate_for_school_id(repo, s, YEAR, ROSTER_SEED) for s in SCHOOLS)
    if slot is not None:
        archive = CareerRosterArchive(slot / 'career_rosters.sqlite3')
        for roster in rosters:
            archive.save_initial_roster(roster)
        rosters = tuple(archive.roster(YEAR, s) for s in SCHOOLS)
    return repo, rosters, JointTeamFixture.from_rosters(repo, rosters)
