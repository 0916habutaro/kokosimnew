"""Read-only v3 detached history; entry teams own all joint wins/losses."""
from dataclasses import asdict, fields
from . import saved_fictional_tournament as v1
from . import saved_practice_match as practice
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
