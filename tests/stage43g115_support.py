"""Explicit self-created scenario; never copies the 2026 registration."""
from phase2_engine import competition_evidence_gates as gates
from phase2_engine.saved_practice_match import saved_authority
from phase2_engine.registered_full_a_lab_store import digest


def scenario(lab):
    snap, rosters, _, receipt = saved_authority(lab)
    by_id = {r.school_id: r for r in rosters}
    # Real master schools, separately chosen for a three-team fictional test.
    # This is not an assertion that any of these schools enter in 2027.
    groups = (('SCH000196',), ('SCH000197',), ('SCH000202', 'SCH000220'))
    namespace = 'fictional:stage115-owned-demo'
    teams = []
    for n, ids in enumerate(groups, 1):
        members = tuple((sid, by_id[sid].program_id) for sid in ids)
        players = tuple(p.player_id for sid in ids for p in by_id[sid].players[:20//len(ids)])
        teams.append(gates.EntryTeam(f'{namespace}:team{n}', members, players))
    teams = tuple(teams)
    def evidence(part):
        return gates.Evidence(gates.Authority.FICTIONAL_DECLARATION, 2027,
                              'self-created declaration/' + part, 'stage115_explicit_demo_v1')
    comp = snap.repo.competition('CMP000041')
    return gates.CompetitionRequest('CMP000041', 2027, comp['competition_type'], namespace,
        gates.EntrySet(evidence('entries'), teams),
        gates.JointComposition(evidence('joint'), ((teams[2].entry_team_id, teams[2].programs),)),
        gates.Qualification(evidence('qualification'), tuple(gates.QualificationDecision(t.entry_team_id, True, 'saved_prior_year', False)
                            for t in teams), digest(receipt)),
        gates.DistrictRules(evidence('district'), 'fictional_yamanashi_v1', 'scenario-district',
            tuple((s, p, 'scenario-district') for t in teams for s, p in t.programs)),
        gates.SeedRules(evidence('seed'), 'fictional_seed_v1', ((teams[0].entry_team_id, 1),)),
        gates.DrawRules(evidence('draw'), 'single_elimination', 3, 4, 1),
        gates.Schedule(evidence('date-envelope'), ('2027-07-01', '2027-07-03')))
