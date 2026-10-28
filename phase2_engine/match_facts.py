"""保存された試合を、日付の確定した実試合として扱えるか判定する。"""
from datetime import date


MATCH_DATE_SOURCES = frozenset(('stage_date_list', 'runtime_wave_v1',
                                'national_day_plan_v1', 'game_projection_v1', 'projected_v1'))


def actual_match_date(row):
    if (row.get('score_source') != 'ability_model_v1'
            or row.get('date_source') not in MATCH_DATE_SOURCES
            or not row.get('team1_id') or not row.get('team2_id')
            or row['team1_id'] == row['team2_id']):
        return None
    a, b = row.get('team1_score'), row.get('team2_score')
    if type(a) is not int or type(b) is not int or min(a, b) < 0 or a == b:
        return None
    try:
        return date.fromisoformat(row.get('match_date', ''))
    except (ValueError, TypeError):
        return None
