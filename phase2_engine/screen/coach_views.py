"""監督の人物・在任イベントを、セーブを変更せず画面用に読む。"""
from __future__ import annotations

from datetime import date, timedelta

from ..school_year import school_year_of
from ..match_facts import actual_match_date
from ..competition_records import NATIONAL


ABILITY_LABELS = (
    ('reputation', '監督評判', '高いほど、翌年度以降に入学する新入生の質が上がります。'),
    ('development', '育成力', '高いほど、毎月の練習による成長が増えます。'),
    ('pitching_change', '継投傾向', '高いほど早めの投手交代、低いほど長い起用を好みます。球数制限を優先します。'),
    ('player_selection', '選手起用傾向', '同程度の能力なら、高いほど下級生、低いほど上級生を優先します。投手は実能力同点時のみです。'),
)
REASONS = {'transfer': '異動', 'retirement': '退任'}


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
        on = actual_match_date(row)
        if on is None or not first <= on.isoformat() <= last:
            continue
        a, b = row.get('team1_score'), row.get('team2_score')
        for sid, won in ((row['team1_id'], a > b), (row['team2_id'], b > a)):
            coach = book.for_school(sid, on=on)
            if coach is not None and coach.coach_id == coach_id:
                wins += won
                losses += not won
    return {'wins': wins, 'losses': losses, 'games': wins + losses,
            'from_date': first, 'through_date': last}


RECORD_CATEGORIES = (
    ('spring_koshien', '春の甲子園'), ('summer_koshien', '夏の甲子園'),
    ('spring_prefectural', '春季都道府県大会'), ('autumn_prefectural', '秋季都道府県大会'),
    ('summer_local', '夏の地方大会'), ('spring_regional', '春季地区大会'),
    ('autumn_regional', '秋季地区大会'),
)


def tournament_record(rows, book, coach_id, today, periods, names):
    """出場と成績決定を別々の試合日に帰属。不戦の公式結果自体は変更しない。"""
    first, on = f'{book.first_year}-04-01', today.isoformat()
    summaries = {key: {'key': key, 'label': label, 'appearances': 0 if key in NATIONAL else None,
                       'championships': 0, 'best_finish': None, 'best_depth': -1}
                 for key, label in RECORD_CATEGORIES}
    records, references = [], []
    appearances, titles = set(), set()

    def commanded(sid, day):
        if not day or not first <= day <= on:
            return False
        coach = book.for_school(sid, on=date.fromisoformat(day))
        return coach is not None and coach.coach_id == coach_id

    for row in rows:
        key, sid = row['category'], row['school_id']
        if key not in summaries:
            continue
        complete = bool(row['complete'] and row['completed_on'] and row['completed_on'] <= on)
        appeared = key in NATIONAL and commanded(sid, row['first_game_date'])
        finished = complete and commanded(sid, row['decision_date']) and bool(row['finish'])
        day = row['decision_date'] if finished else row['first_game_date']
        base = {**row, 'school_year': row['year'], 'appearance': appeared,
                'personal_finish': row['finish'] if finished else None}
        if appeared or finished:
            base['school_name'] = names(sid, day)
            base['current_school_name'] = names(sid, on)
            records.append(base)
            summary = summaries[key]
            identity = (row['year'], row['competition_id'])
            if appeared and identity not in appearances:
                summary['appearances'] += 1
                appearances.add(identity)
            if finished:
                if row['finish'] == '優勝' and identity not in titles:
                    summary['championships'] += 1
                    titles.add(identity)
                if row['depth'] > summary['best_depth']:
                    summary['best_finish'], summary['best_depth'] = row['finish'], row['depth']
        if complete and row['resolution']:
            # これは人物の実績ではなく、開催期間（予定日を含む）と在任期間が
            # 重なる学校の参考情報。決定戦の監督は推測しない。
            start, end = row['period_start'], row['period_end']
            if not start or not end or end < first or start > on:
                continue
            related = any(p['school_id'] == sid and p['start_date'] <= min(end, on)
                          and (p['end_date'] is None or p['end_date'] > max(start, first))
                          for p in periods)
            if related:
                references.append({**base, 'school_name': names(sid, max(start, first)),
                                   'current_school_name': names(sid, on),
                                   'personal_finish': None, 'label': '不戦決着・帰属未確定'
                                   if row['resolution'].startswith('不戦') else '実施・日付未確定'})
    order = lambda r: (r['year'], r['competition_id'], r['school_id'])
    return {'summary': list(summaries.values()), 'records': sorted(records, key=order, reverse=True),
            'references': sorted(references, key=order, reverse=True)}
