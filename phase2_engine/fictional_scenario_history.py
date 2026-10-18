"""Stage118 read-only history across several independently audited fictional scenarios.

Every stream is keyed by (year, record_kind, namespace) and match IDs must be
disjoint across all streams. Each bracket store re-audits its own SQLite and
the saved source before a view is built. A joint entry's games belong only to
that entry: they are never added to a member school's standalone record.
Nothing is written to any store, product archive, outcomes table or master.
"""
from dataclasses import asdict, fields

from . import registered_full_a_lab_store as codec
from . import saved_fictional_bracket as v2
from . import saved_fictional_tournament as v1
from . import saved_practice_match as practice
from .registered_full_a_contract import RegisteredBatterStatsV1, RegisteredPitcherStatsV1

OFFICIAL_2027 = dict(official_2027_entry=None, official_2027_qualification=None,
                     official_2027_joint_continuation=None, official_2027_schedule=None,
                     official_2027_ranking=None, official_2027_outcomes=None)


def scenario_history(bracket_stores, *, practice_store=None, v1_store=None):
    """Snapshot every store now; the first store also audits practice/v1 links."""
    stores = tuple(bracket_stores)
    if not stores or any(type(s) is not v2.FictionalBracketStore for s in stores):
        raise ValueError('owned Stage117-v2 fictional bracket stores required')
    lab = stores[0].lab
    if any(s.lab is not lab for s in stores) or len({id(s) for s in stores}) != len(stores):
        raise ValueError('distinct bracket stores on the same owned saved year required')
    receipts = {codec.canonical(codec.strict_json(s.capability.contract_json)['source_receipt']) for s in stores}
    if len(receipts) != 1:
        raise ValueError('every scenario must bind the same saved source receipt')
    views = (stores[0].snapshot(practice_store=practice_store, v1_store=v1_store),
             *(s.snapshot() for s in stores[1:]))
    return ScenarioHistory(views)


def _totals(rows, cls):
    names = [f.name for f in fields(cls) if f.type in (int, 'int') and f.name != 'year']
    return {name: sum(getattr(r, name) for r in rows) for name in names}


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
        self.streams = [s for s in first._streams if s[1] != v2.KIND]
        self.streams += [(v2.YEAR, v2.KIND, v.plan.namespace, v.results) for v in views]
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
