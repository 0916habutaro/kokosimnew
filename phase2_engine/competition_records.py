"""監督と独立した、本大会の出場と確定成績の小さな学校別索引。"""
from .match_facts import actual_match_date
from .tournament_runtime import MainTournamentRuntimeState


CATEGORIES = {
    'national_invitational': 'spring_koshien',
    'national_championship': 'summer_koshien',
    'spring_prefectural': 'spring_prefectural',
    'autumn_prefectural': 'autumn_prefectural',
    'summer_local_qualifier': 'summer_local',
    'spring_regional': 'spring_regional',
    'autumn_regional': 'autumn_regional',
}
NATIONAL = frozenset(('spring_koshien', 'summer_koshien'))
BYE_SOURCES = frozenset(('bye', 'walkover', 'forfeit'))


def main_runtime(scheduled) -> MainTournamentRuntimeState | None:
    runtime = scheduled.runtime
    return runtime if isinstance(runtime, MainTournamentRuntimeState) else getattr(runtime, 'main_runtime', None)


def _finish(outcome, school):
    if school == outcome.champion_school_id:
        return '優勝', 100
    if school == outcome.runner_up_school_id:
        return '準優勝', 50
    if school in outcome.eliminated_by_round.get(outcome.total_rounds - 1, []):
        return 'ベスト4', 25
    if school in outcome.eliminated_by_round.get(outcome.total_rounds - 2, []):
        return 'ベスト8', 12
    for round_no, schools in outcome.eliminated_by_round.items():
        if school in schools:
            rounds = outcome.bracket_size.bit_length() - 1
            best = 2 ** (rounds - int(round_no) + 1)
            return ('ベスト16', 6) if best == 16 else (f'{round_no}回戦敗退', int(round_no))
    return '', 0


def competition_records(year, cid, scheduled, competition, calendar=None, name='', confirmed_on='',
                        school_ids=None):
    """MAINの登録・実試合・結果を投影するだけ。進行・名簿生成・乱数は呼ばない。"""
    category = CATEGORIES.get(competition.get('competition_type'))
    if category is None:
        return []
    main = main_runtime(scheduled)
    if main is None:
        return []
    complete = scheduled.is_complete
    # 確定したランタイムの公式結果。順位決めの乱数や試合の再計算は不要。
    outcome = main if complete else None
    schools = list(main.entrant_school_ids) if category in NATIONAL else (
        [outcome.champion_school_id] if outcome and outcome.champion_school_id else [])
    if school_ids is not None:
        schools = [s for s in schools if s in school_ids]
    if not schools:
        return []
    matches = [m.public_dict() for m in scheduled.matches.values()
               if m.stage_code == 'MAIN' and m.status == 'completed']
    calendar = calendar or {}
    dates = [m.get('match_date', '') for m in matches]
    start = min(filter(None, [calendar.get('start_date', ''), *dates]), default='')
    end = max(filter(None, [calendar.get('end_date', ''), *dates]), default='')
    completed_on = max((m.get('completed_on', '') or m.get('match_date', '') for m in matches), default='')
    out = []
    for sid in schools:
        own = [m for m in matches if sid in (m['team1_id'], m['team2_id'])]
        actual = [m for m in own if m.get('score_source') == 'ability_model_v1']
        first = None
        if actual:
            first_round = min(m['round_no'] for m in actual)
            opening = [m for m in actual if m['round_no'] == first_round]
            if len(opening) == 1 and actual_match_date(opening[0]) is not None:
                first = opening[0]['match_date']
        finish, depth = _finish(outcome, sid) if outcome else ('', 0)
        decisive = [m for m in own if (
            m['round_no'] == main.total_rounds if finish in ('優勝', '準優勝')
            else sid in main.eliminated_by_round.get(m['round_no'], [])
        ) and (m.get('winner_id') == sid if finish == '優勝' else m.get('loser_id') == sid)]
        decision = decisive[0] if complete and len(decisive) == 1 else None
        decision_day = actual_match_date(decision) if decision is not None else None
        resolution = ''
        if finish and decision_day is None:
            if decision and decision.get('score_source') in BYE_SOURCES:
                resolution = '不戦勝' if decision.get('winner_id') == sid else '不戦敗'
            elif decision is None and main.bracket_size == 1 and finish == '優勝':
                resolution = '不戦勝（決勝未実施）'
            else:
                resolution = '決定戦の実施・日付を確認できない'
        out.append({'year': year, 'competition_id': cid, 'school_id': sid,
                    'competition_name': name or scheduled.competition_name,
                    'category': category, 'complete': complete,
                    'completed_on': (confirmed_on or completed_on) if complete else '',
                    'first_game_date': first,
                    'finish': finish, 'depth': depth,
                    'decision_date': decision_day.isoformat() if decision_day else None,
                    'resolution': resolution, 'period_start': start, 'period_end': end})
    return out


def season_records(season, repo, names=None):
    return [row for cid, scheduled in season.competitions.items()
            for row in competition_records(season.year, cid, scheduled,
                repo.competitions.get(cid, {}), season.calendar_rows.get(cid, {}),
                (names or {}).get(cid, ''), season.current_date.isoformat())]
