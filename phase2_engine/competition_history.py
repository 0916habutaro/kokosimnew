"""確定ランタイムから大会別ベスト8を投影する。進行・結果の再計算はしない。"""
from .competition_records import main_runtime as direct_main_runtime


FINISHES = ('優勝', '準優勝', 'ベスト4', 'ベスト8')


def result_main(scheduled):
    """シード決定→予選→MAINの複合方式も、予選内部の確定MAINを参照する。"""
    main = direct_main_runtime(scheduled)
    if main is None:
        qualifier = getattr(scheduled.runtime, 'qualifier_runtime', None)
        main = getattr(qualifier, 'main_runtime', None)
    return main


def best8_record(season, cid, name=''):
    scheduled = season.competitions.get(cid)
    calendar = season.calendar_rows.get(cid, {})
    days = [calendar.get('start_date', '')]
    days += [dates[0] for dates in getattr(season, 'stage_date_lists', {}).get(cid, {}).values() if dates]
    if scheduled is not None:
        days += [m.match_date for m in scheduled.matches.values()]
    start = min(filter(None, days), default='')
    today = season.current_date.isoformat()
    main = result_main(scheduled) if scheduled is not None else None
    complete = scheduled is not None and scheduled.is_complete
    if complete and main is not None and main.is_complete:
        status = '完了'
    elif ((scheduled is not None and any(
            m.status != 'pending' or m.match_date <= today for m in scheduled.matches.values()))
          or (start and start <= today)):
        status = '進行中'
    else:
        status = '未開催'
    groups = {finish: [] for finish in FINISHES}
    if status == '完了':
        ids = ([main.champion_school_id], [main.runner_up_school_id],
               main.eliminated_by_round.get(main.total_rounds - 1, []) if main.total_rounds >= 2 else [],
               main.eliminated_by_round.get(main.total_rounds - 2, []) if main.total_rounds >= 3 else [])
        seen = set()
        for finish, schools in zip(FINISHES, ids):
            for sid in schools:
                if not sid or sid in seen:
                    continue
                seen.add(sid)
                # 改称前の結果は当時の名前で表示する。予選の日付は使わない。
                days = [m.match_date for m in scheduled.matches.values()
                        if m.stage_code == 'MAIN' and m.status == 'completed'
                        and sid in (m.team1_id, m.team2_id) and m.match_date]
                groups[finish].append({'school_id': sid,
                                       'date': max(days, default=calendar.get('end_date') or start)})
    elif complete:
        status = '記録なし'  # MAINの確定結果がないものを試合から推測しない
    return {'school_year': season.year, 'competition_id': cid,
            'competition_name': name or (scheduled.competition_name if scheduled else ''),
            'status': status, 'groups': groups}


def season_best8(season, names=None):
    return [best8_record(season, cid, (names or {}).get(cid, ''))
            for cid in season.annual_templates]
