"""監督の人物・在任イベントを、セーブを変更せず画面用に読む。"""
from __future__ import annotations

from datetime import date, timedelta

from ..school_year import school_year_of


ABILITY_LABELS = (
    ('reputation', '監督評判', '高いほど、翌年度以降に入学する新入生の質が上がります。'),
    ('development', '育成力', '高いほど、毎月の練習による成長が増えます。'),
    ('pitching_change', '継投傾向', '高いほど早めの投手交代、低いほど長い起用を好みます。球数制限を優先します。'),
    ('player_selection', '選手起用傾向', '同程度の能力なら、高いほど下級生、低いほど上級生を優先します。投手は実能力同点時のみです。'),
)
REASONS = {'transfer': '異動', 'retirement': '退任'}
MATCH_DATE_SOURCES = frozenset(('stage_date_list', 'runtime_wave_v1',
                                'national_day_plan_v1', 'game_projection_v1', 'projected_v1'))


class CoachHistory:
    """画面だけの索引。人物・学校ごとの参照を共有し、全年度の人物コピーは作らない。"""

    def __init__(self, book):
        self.book = book
        self.event_count = len(book.events)
        self.by_coach = {}
        self.by_school = {}
        active = {}
        for event in book.events:
            if event.from_school_id:
                previous = active.pop(event.coach_id, None)
                if previous is None or previous['school_id'] != event.from_school_id:
                    raise ValueError('監督の在任履歴が一致しません')
                previous['end_date'] = event.date
                previous['end_reason'] = event.kind
            if event.to_school_id:
                row = {'coach_id': event.coach_id, 'school_id': event.to_school_id,
                       'start_date': event.date, 'end_date': None, 'end_reason': None,
                       'initial': event.kind == 'initial'}
                active[event.coach_id] = row
                self.by_coach.setdefault(event.coach_id, []).append(row)
                self.by_school.setdefault(event.to_school_id, []).append(row)

    def periods(self, rows, today, names):
        on = today.isoformat()
        first = f'{self.book.first_year}-04-01'
        out = []
        for row in rows:
            start = row['start_date']
            if start > on:
                continue
            end = row['end_date'] if row['end_date'] and row['end_date'] <= on else None
            last = (date.fromisoformat(end) - timedelta(days=1)).isoformat() if end else None
            a = date.fromisoformat(start)
            if end:
                b = date.fromisoformat(end)
                years = b.year - a.year - ((b.month, b.day) < (a.month, a.day))
            else:
                years = school_year_of(today) - school_year_of(a) + 1
            sid = row['school_id']
            configured = row['initial'] and start < first
            out.append({
                'coach_id': row['coach_id'],
                'name': self.book.coaches[row['coach_id']].display_name,
                'school_id': sid, 'school_name': names(sid, max(start, first)),
                'current_school_name': names(sid, on),
                'name_basis': '開始時' if configured else '就任時',
                'start_date': start, 'end_date': end, 'last_day': last,
                'appointment_year': int(start[:4]),
                'departure_year': int(end[:4]) if end else None,
                'tenure_years': years,
                'status': REASONS.get(row['end_reason'], '離任') if end else '現任',
                'configured_past': configured,
            })
        return out

    def school(self, school_id, today, names):
        return self.periods(self.by_school.get(school_id, ()), today, names)

    def coach(self, coach_id, today, names):
        person = self.book.coaches.get(coach_id)
        if person is None:
            raise ValueError('その監督はありません')
        periods = self.periods(self.by_coach.get(coach_id, ()), today, names)
        if not periods:
            raise ValueError('この日時点の在任記録がありません')
        current = next((p for p in reversed(periods) if p['end_date'] is None), None)
        retired = bool(person.retired_on and person.retired_on <= today.isoformat())
        return {
            'coach_id': coach_id, 'name': person.display_name,
            'age': school_year_of(today) - person.birth_year, 'birth_year': person.birth_year,
            'status': '退任済み' if retired else '現役',
            'retired_on': person.retired_on if retired else None,
            'current_school': ({'school_id': current['school_id'],
                                'name': current['current_school_name']} if current else None),
            'appointment_year': current['appointment_year'] if current else None,
            'tenure_years': current['tenure_years'] if current else None,
            'abilities': [{'key': key, 'label': label, 'value': getattr(person, key),
                           'description': description} for key, label, description in ABILITY_LABELS],
            'periods': periods, 'as_of': today.isoformat(),
            'simulation_start': f'{self.book.first_year}-04-01',
        }


def official_record(rows, book, coach_id, today):
    """実際に行った能力シミュレーターの公式戦のみ。開始前の設定・不戦は加算しない。"""
    first = f'{book.first_year}-04-01'
    last = today.isoformat()
    wins = losses = 0
    for row in rows:
        day = row.get('match_date', '')
        if (row.get('score_source') != 'ability_model_v1'
                or row.get('date_source') not in MATCH_DATE_SOURCES
                or not isinstance(day, str) or not first <= day <= last
                or not row.get('team1_id') or not row.get('team2_id')
                or row['team1_id'] == row['team2_id']):
            continue
        a, b = row.get('team1_score'), row.get('team2_score')
        if (type(a) is not int or type(b) is not int or a < 0 or b < 0 or a == b):
            continue
        try:
            on = date.fromisoformat(day)
        except ValueError:
            continue
        for sid, won in ((row['team1_id'], a > b), (row['team2_id'], b > a)):
            coach = book.for_school(sid, on=on)
            if coach is not None and coach.coach_id == coach_id:
                wins += won
                losses += not won
    return {'wins': wins, 'losses': losses, 'games': wins + losses,
            'from_date': first, 'through_date': last}
