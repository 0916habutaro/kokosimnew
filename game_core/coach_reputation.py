"""人物の実績を一度だけ評価する監督評判。学校評判・試合乱数とは独立。"""
from dataclasses import dataclass, replace
from datetime import date
import math

from phase2_engine.competition_records import competition_records, coach_credits, commanding_coach_id
from phase2_engine.match_facts import actual_match_date
from phase2_engine.school_year import school_year_of
from .ability_config import load_config


@dataclass(frozen=True)
class CoachReputationAssessment:
    update_year: int
    period_start: str
    period_end: str
    before: int
    after: int
    target: float
    schools: dict
    achievements: tuple


@dataclass(init=False)
class CoachReputation:
    config: dict
    updated_year: int
    completed: set
    seen_matches: dict
    seen_entries: dict
    pending: dict
    history: dict
    residuals: dict

    def __init__(self, root, first_year):
        self.config = load_config(root / 'config/coaches/coach_reputation_v1.json',
                                  expected_config_id='coach_reputation_v1').payload
        self._validate()
        self.updated_year = first_year
        self.completed = set()
        self.seen_matches = {}
        self.seen_entries = {}
        self.pending = {}
        self.history = {}
        self.residuals = {}

    def _validate(self):
        c = self.config
        scalars = ('minimum', 'maximum', 'neutral', 'match_prior_games', 'match_target_span',
                   'response', 'max_annual_change', 'national_appearance_target')
        values = [c[k] for k in scalars] + list(c['national_finish_targets'].values()) + list(c['championship_targets'].values())
        if (any(type(v) not in (int, float) or not math.isfinite(v) for v in values)
                or type(c['enabled']) is not bool or c['first_update_year'] != 2027
                or (c['minimum'], c['neutral'], c['maximum']) != (1, 50, 100)
                or not 0 < c['response'] <= 1 or c['match_prior_games'] <= 0
                or not 0 <= c['match_target_span'] <= c['maximum'] - c['neutral']
                or type(c['max_annual_change']) is not int or not 0 <= c['max_annual_change'] < c['maximum']
                or any(not c['neutral'] <= v <= c['maximum'] for v in [c['national_appearance_target'],
                    *c['national_finish_targets'].values(), *c['championship_targets'].values()])):
            raise ValueError('invalid coach annual reputation configuration')

    def _stats(self, year, cid):
        if year < self.updated_year:
            raise ValueError('coach achievement was not collected before its assessment')
        return self.pending.setdefault(year, {}).setdefault(cid, {'schools': {}, 'achievements': []})

    @staticmethod
    def _school(stats, school):
        return stats['schools'].setdefault(school, {'wins': 0, 'losses': 0})

    def collect(self, book, seasons, today):
        """毎日の確定済み試合を採る。進行・順位再抽選・履歴DBの展開はしない。"""
        for year, season in sorted(seasons.items()):
            for cid, scheduled in sorted(getattr(season, 'competitions', {}).items()):
                key = (year, cid)
                if key in self.completed:
                    continue
                seen = self.seen_matches.setdefault(key, set())
                future = False
                for mid, match in scheduled.matches.items():
                    if mid in seen or match.status != 'completed':
                        continue
                    row = match.public_dict()
                    on = actual_match_date(row)
                    if on is not None and on > today:
                        future = True
                        continue
                    seen.add(mid)
                    if on is None:
                        continue
                    for side in ('team1_id', 'team2_id'):
                        school = row[side]
                        coach = commanding_coach_id(book, school, on.isoformat(), today)
                        if coach is None:
                            continue
                        score = row['team1_score'] > row['team2_score']
                        won = score if side == 'team1_id' else not score
                        stats = self._stats(school_year_of(on), coach)
                        self._school(stats, school)['wins' if won else 'losses'] += 1
                if future:
                    continue
                metadata = getattr(getattr(season, 'repo', None), 'competitions', {}).get(cid, {})
                records = competition_records(year, cid, scheduled, metadata,
                    getattr(season, 'calendar_rows', {}).get(cid, {}), confirmed_on=today.isoformat())
                entered = self.seen_entries.setdefault(key, set())
                for row in records:
                    appearance, finish = coach_credits(row, book, today)
                    for kind, coach, day in (('appearance', appearance, row['first_game_date']),
                                              ('finish', finish, row['decision_date'])):
                        if coach is None or (kind == 'appearance' and row['school_id'] in entered):
                            continue
                        if kind == 'appearance':
                            entered.add(row['school_id'])
                            target = self.config['national_appearance_target']
                            confirmed = date.fromisoformat(day)
                        else:
                            target = (self.config['national_finish_targets'].get(row['finish'])
                                      if row['category'] in ('spring_koshien', 'summer_koshien')
                                      else self.config['championship_targets'].get(row['category']))
                            if target is None:
                                continue
                            confirmed = today
                        stats = self._stats(school_year_of(confirmed), coach)
                        self._school(stats, row['school_id'])
                        stats['achievements'].append({'year': year, 'competition_id': cid,
                            'school_id': row['school_id'], 'kind': kind, 'finish': row['finish'] if kind == 'finish' else '',
                            'commanded_on': day, 'confirmed_on': confirmed.isoformat(), 'target': target})
                if scheduled.is_complete:
                    self.completed.add(key)
                    self.seen_matches.pop(key, None)
                    self.seen_entries.pop(key, None)

    def update(self, book, today):
        if ((today.month, today.day) != (4, 1) or today.year < self.config['first_update_year']
                or today.year <= self.updated_year):
            return False
        if today.year != self.updated_year + 1:
            raise ValueError('coach reputation must be updated in consecutive school years')
        start = f'{self.updated_year}-04-01'
        end = f'{today.year}-03-31'
        rows = self.pending.pop(self.updated_year, {})
        c = self.config
        for cid, stats in sorted(rows.items()):
            coach = book.coaches[cid]
            wins = sum(s['wins'] for s in stats['schools'].values())
            losses = sum(s['losses'] for s in stats['schools'].values())
            match_target = c['neutral'] + c['match_target_span'] * (wins - losses) / (wins + losses + c['match_prior_games'])
            target = max([match_target, *(a['target'] for a in stats['achievements'])])
            value = coach.reputation
            if c['enabled']:
                delta = c['response'] * (target - value) + self.residuals.get(cid, 0.0)
                limit = c['max_annual_change']
                proposed = max(c['minimum'], min(c['maximum'], value + max(-limit, min(limit, delta))))
                value = round(proposed)
                self.residuals[cid] = round(proposed - value, 8)
                book.coaches[cid] = replace(coach, reputation=value)
            self.history.setdefault(cid, []).append(CoachReputationAssessment(today.year, start, end,
                coach.reputation, value, round(target, 8), stats['schools'], tuple(stats['achievements'])))
        self.updated_year = today.year
        return True
