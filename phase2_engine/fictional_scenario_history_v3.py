"""Read-only v3 detached history; entry teams own all joint wins/losses."""
from dataclasses import asdict, fields
from . import saved_fictional_tournament as v1
from . import saved_practice_match as practice
from . import saved_fictional_bracket_v3 as v3
from . import registered_full_a_lab_store as codec
from .saved_fictional_bracket_v3 import KIND, YEAR
from .fictional_bracket_oracle import progression
from .registered_full_a_contract import RegisteredBatterStatsV1, RegisteredPitcherStatsV1

def _totals(rows, cls):
    names = [f.name for f in fields(cls) if f.type in (int, 'int') and f.name != 'year']
    return {name: sum(getattr(r, name) for r in rows) for name in names}


class FictionalBracketView:
    """Detached verified history. Joint wins belong exclusively to entry teams."""
    def __init__(self, prepared, request, results, practice_view, v1_view):
        authority, self.plan, self.bracket, self.teams, _ = prepared
        self._source, self._rosters, self._lineage, _ = authority
        self.request, self.results, self.v1 = request, results, v1_view
        self.ledger, self.ranks = progression(self.plan, request, results)
        self.complete = len(results) == len(self.plan.games)
        self.fictional_scenario_champion = self.ranks[0][1] if self.complete else None
        self.official_year_verified = self.product_season_start_authorized = False
        self._streams = [(2026, v1.KIND, self._source.results[0].competition_id, self._source.results)]
        if practice_view:
            self._streams.append((2027, practice.KIND, practice.SCOPE, practice_view.results))
        if v1_view:
            self._streams.append((2027, v1.KIND, v1_view.plan.namespace, v1_view.results))
        self._streams.append((2027, KIND, self.plan.namespace, results))
        self._people = {p.player_id: p for r in (*self._source.rosters, *self._rosters) for p in r.players}

    def next_pair(self):
        if self.complete:
            return None
        return self.bracket.pair(len(self.results) + 1, self.results)

    @staticmethod
    def _record(game, kind, namespace):
        return dict(year=game.year, record_kind=kind, namespace=namespace,
                    match_id=game.match_id, result=game.to_dict())

    def team(self, entry_team_id):
        entry = next((t for t in self.request.entries.teams if t.entry_team_id == entry_team_id), None)
        if entry is None:
            raise ValueError('unknown fictional entry team')
        games = [g for g in self.results if entry_team_id in (g.team1_id, g.team2_id)]
        return dict(entry_team_id=entry_team_id, year=YEAR, record_kind=KIND, namespace=self.plan.namespace,
            programs=entry.programs, joint=len(entry.programs) > 1,
            bye=entry_team_id in self.bracket.byes,
            wins=sum(g.winner_id == entry_team_id for g in games), losses=sum(g.loser_id == entry_team_id for g in games),
            matches=[self._record(g, KIND, self.plan.namespace) for g in games],
            scenario_rank=next((r[0] for r in self.ranks if r[1] == entry_team_id), None),
            official_2027_ranking=None)

    def school(self, school_id):
        if school_id not in {r.school_id for r in self._rosters}:
            raise ValueError('unknown saved school')
        tids = {t.team_id for t in self._source.registration.teams if school_id in t.school_ids}
        tids.add(f'LAB114:2027:SCHOOL:{school_id}')
        records = [self.team(t.entry_team_id) for t in self.request.entries.teams
                   if school_id in {sid for sid, _ in t.programs}]
        tids.update(r['entry_team_id'] for r in records)
        v1_records = []
        if self.v1:
            v1_records = [self.v1.team(t.entry_team_id) for t in self.v1.request.entries.teams
                          if school_id in {sid for sid, _ in t.programs}]
            tids.update(r['entry_team_id'] for r in v1_records)
        history = []
        for year, kind, namespace, games in self._streams:
            rosters = self._source.rosters if year == 2026 else self._rosters
            history.append(dict(year=year, record_kind=kind, namespace=namespace,
                roster=next(r.to_dict() for r in rosters if r.school_id == school_id),
                matches=[self._record(g, kind, namespace) for g in games if tids.intersection((g.team1_id, g.team2_id))]))
        return dict(school_id=school_id, history=history, fictional_team_records=records,
            v1_fictional_team_records=v1_records,
            standalone_wins=sum(r['wins'] for r in records if not r['joint']),
            standalone_losses=sum(r['losses'] for r in records if not r['joint']),
            v1_standalone_wins=sum(r['wins'] for r in v1_records if not r['joint']),
            v1_standalone_losses=sum(r['losses'] for r in v1_records if not r['joint']),
            product_season_start_authorized=False, official_2027_outcomes=None, official_2027_schedule=None,
            official_2027_entry=None, official_2027_ranking=None,
            official_2027_qualification=None, official_2027_joint_continuation=None)

    def player(self, player_id):
        person = self._people.get(player_id)
        if person is None:
            raise ValueError('unknown permanent player ID')
        history = []
        for year, kind, namespace, games in self._streams:
            rosters = self._source.rosters if year == 2026 else self._rosters
            current = next((p for r in rosters for p in r.players if p.player_id == player_id), None)
            appearances = []
            for game in games:
                batting = [asdict(r) for r in game.batter_stats if r.player_id == player_id and r.plate_appearances]
                pitching = [asdict(r) for r in game.pitcher_stats if r.player_id == player_id and r.batters_faced]
                if batting or pitching:
                    appearances.append(dict(year=year, record_kind=kind, namespace=namespace, match_id=game.match_id,
                                            entry_team_id=(batting or pitching)[0]['team_id'],
                                            batting=batting, pitching=pitching))
            history.append(dict(year=year, record_kind=kind, namespace=namespace,
                state='active' if current else ('not_yet_enrolled' if year < person.entry_year else 'graduated'),
                profile=current.to_dict() if current else None, appearances=appearances))
        batting = [r for g in self.results for r in g.batter_stats if r.player_id == player_id]
        pitching = [r for g in self.results for r in g.pitcher_stats if r.player_id == player_id]
        return dict(player_id=player_id, origin_school_id=person.school_id, program_id=person.program_id,
            entry_year=person.entry_year, transition=next(state for pid, _, state, _, _ in self._lineage if pid == player_id),
            history=history, scenario_namespace=self.plan.namespace,
            scenario_batting_totals=_totals(batting, RegisteredBatterStatsV1),
            scenario_pitching_totals=_totals(pitching, RegisteredPitcherStatsV1),
            product_season_start_authorized=False)


def scenario_history(bracket_stores, *, practice_store=None, v1_store=None):
    """Snapshot every store now; the first store also audits practice/v1 links."""
    stores = tuple(bracket_stores)
    if not stores or any(type(s) is not v3.FictionalBracketStore for s in stores):
        raise ValueError('owned Stage119-v3 fictional bracket stores required')
    lab = stores[0].lab
    if any(s.lab is not lab for s in stores) or len({id(s) for s in stores}) != len(stores):
        raise ValueError('distinct bracket stores on the same owned saved year required')
    receipts = {codec.canonical(codec.strict_json(s.capability.contract_json)['source_receipt']) for s in stores}
    if len(receipts) != 1:
        raise ValueError('every scenario must bind the same saved source receipt')
    views = (stores[0].snapshot(practice_store=practice_store, v1_store=v1_store),
             *(s.snapshot() for s in stores[1:]))
    return ScenarioHistory(views)



class ScenarioHistory:
    """Detached view; streams never share a namespace, scope or match ID."""

    def __init__(self, views):
        first = views[0]
        self._source, self._rosters, self._lineage = first._source, first._rosters, first._lineage
        self.scenarios = {v.plan.namespace: v for v in views}
        scopes = {v.plan.scope for v in views}
        if len(self.scenarios) != len(views) or len(scopes) != len(views):
            raise ValueError('separate scenario namespace and scope required')
        if first.v1 is not None and first.v1.plan.namespace in self.scenarios:
            raise ValueError('separate scenario namespace required')
        # Base streams come from the first audited view: 2026, practice, Stage116 v1.
        self.streams = [s for s in first._streams if s[1] != v3.KIND]
        self.streams += [(v3.YEAR, v3.KIND, v.plan.namespace, v.results) for v in views]
        keys = [(year, kind, namespace) for year, kind, namespace, _ in self.streams]
        ids = [g.match_id for *_, games in self.streams for g in games]
        if len(set(keys)) != len(keys) or len(set(ids)) != len(ids):
            raise ValueError('streams must be separated by year/kind/namespace/match_id')
        self._v1 = first.v1
        self._people = first._people
        self.official_year_verified = self.product_season_start_authorized = False

    def stream_summary(self):
        return [dict(year=y, record_kind=k, namespace=n, matches=len(g)) for y, k, n, g in self.streams]

    def _entries(self, year, kind, namespace):
        """Entry team IDs per school for exactly one stream."""
        if year == 2026:
            return {sid: {t.team_id for t in self._source.registration.teams if sid in t.school_ids}
                    for sid in {s for t in self._source.registration.teams for s in t.school_ids}}
        if kind == practice.KIND:
            return {r.school_id: {f'LAB114:2027:SCHOOL:{r.school_id}'} for r in self._rosters}
        request = self._v1.request if kind == v1.KIND else self.scenarios[namespace].request
        out = {}
        for entry in request.entries.teams:
            for sid, _ in entry.programs:
                out.setdefault(sid, set()).add(entry.entry_team_id)
        return out

    @staticmethod
    def _record(game, kind, namespace):
        return dict(year=game.year, record_kind=kind, namespace=namespace,
                    match_id=game.match_id, result=game.to_dict())

    def team(self, namespace, entry_team_id):
        view = self.scenarios.get(namespace)
        if view is None:
            raise ValueError('unknown fictional scenario namespace')
        return view.team(entry_team_id)

    def school(self, school_id):
        if school_id not in {r.school_id for r in self._rosters}:
            raise ValueError('unknown saved school')
        history = []
        for year, kind, namespace, games in self.streams:
            tids = self._entries(year, kind, namespace).get(school_id, set())
            rosters = self._source.rosters if year == 2026 else self._rosters
            history.append(dict(year=year, record_kind=kind, namespace=namespace,
                entry_team_ids=sorted(tids),
                roster=next(r.to_dict() for r in rosters if r.school_id == school_id),
                matches=[self._record(g, kind, namespace) for g in games
                         if tids.intersection((g.team1_id, g.team2_id))]))
        scenarios = {}
        for namespace, view in self.scenarios.items():
            records = [view.team(t.entry_team_id) for t in view.request.entries.teams
                       if school_id in {sid for sid, _ in t.programs}]
            single = [r for r in records if not r['joint']]
            scenarios[namespace] = dict(
                standalone_records=single, joint_records=[r for r in records if r['joint']],
                standalone_wins=sum(r['wins'] for r in single), standalone_losses=sum(r['losses'] for r in single))
        return dict(school_id=school_id, history=history, scenarios=scenarios,
            standalone_wins_all_scenarios=sum(s['standalone_wins'] for s in scenarios.values()),
            standalone_losses_all_scenarios=sum(s['standalone_losses'] for s in scenarios.values()),
            product_season_start_authorized=False, **OFFICIAL_2027)

    def player(self, player_id):
        person = self._people.get(player_id)
        if person is None:
            raise ValueError('unknown permanent player ID')
        history = []
        for year, kind, namespace, games in self.streams:
            rosters = self._source.rosters if year == 2026 else self._rosters
            current = next((p for r in rosters for p in r.players if p.player_id == player_id), None)
            appearances = []
            for game in games:
                batting = [asdict(r) for r in game.batter_stats if r.player_id == player_id and r.plate_appearances]
                pitching = [asdict(r) for r in game.pitcher_stats if r.player_id == player_id and r.batters_faced]
                if batting or pitching:
                    appearances.append(dict(year=year, record_kind=kind, namespace=namespace, match_id=game.match_id,
                                            entry_team_id=(batting or pitching)[0]['team_id'],
                                            batting=batting, pitching=pitching))
            history.append(dict(year=year, record_kind=kind, namespace=namespace,
                state='active' if current else ('not_yet_enrolled' if year < person.entry_year else 'graduated'),
                profile=current.to_dict() if current else None, appearances=appearances))
        totals = {}
        for namespace, view in self.scenarios.items():
            batting = [r for g in view.results for r in g.batter_stats if r.player_id == player_id]
            pitching = [r for g in view.results for r in g.pitcher_stats if r.player_id == player_id]
            totals[namespace] = dict(batting=_totals(batting, RegisteredBatterStatsV1),
                                     pitching=_totals(pitching, RegisteredPitcherStatsV1))
        return dict(player_id=player_id, origin_school_id=person.school_id, program_id=person.program_id,
            entry_year=person.entry_year,
            transition=next(state for pid, _, state, _, _ in self._lineage if pid == player_id),
            history=history, scenario_totals=totals, product_season_start_authorized=False)
