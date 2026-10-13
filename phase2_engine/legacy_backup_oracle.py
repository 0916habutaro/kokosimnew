"""Independent read-only SQL/SHA oracle; no archive decoding helpers or replay."""
from contextlib import closing
import hashlib
import json
import sqlite3

TABLES = {
    'historical_matches.sqlite3': {'archive_identity', 'career_years', 'historical_matches',
                                 'historical_competition_outcomes'},
    'career_rosters.sqlite3': {'career_school_rosters', 'career_player_identities'},
}


class Refused(ValueError):
    """Fixed, non-sensitive diagnostic codes only."""


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def sha(raw):
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def ro(path):
    con = sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    con.execute('PRAGMA query_only=ON')
    return con


def facts(root):
    """Independent raw SQL/payload oracle, including every original table.

    No production _ledger/_history_payload/roster decoder calls. DB backup
    may change physical page layout, so compare schema and full logical rows.
    """
    result = {}
    for name, allowed in TABLES.items():
        with closing(ro(root / name)) as con:
            if con.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise Refused('sqlite_integrity')
            schema = con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master "
                                 "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
            tables = {r[1] for r in schema if r[0] == 'table'}
            if not tables <= allowed:
                raise Refused('unknown_original_table')
            rows = {t: con.execute('SELECT * FROM "' + t + '" ORDER BY 1,2').fetchall()
                    for t in sorted(tables)}
            result[name] = (schema, rows)
            con.row_factory = sqlite3.Row
            if name == 'historical_matches.sqlite3':
                matches = con.execute('SELECT * FROM historical_matches ORDER BY year,competition_id,match_id').fetchall()
                headers = {r['year']: r for r in con.execute('SELECT * FROM career_years')}
                for row in matches:
                    p = json.loads(row['payload_json'])
                    if sha(row['payload_json']) != row['record_sha256'] or any(
                            p[k] != row[k] for k in ('year', 'competition_id', 'match_id',
                            'match_date', 'date_source', 'team1_id', 'team2_id',
                            'team1_score', 'team2_score', 'score_source')) or row['year'] not in headers:
                        raise Refused('raw_match_mismatch')
                    # Older score-only/bye records remain exactly as stored.
                    if p.get('inning_scores') is None:
                        continue
                    for sid, score in ((p['team1_id'], p['team1_score']), (p['team2_id'], p['team2_score'])):
                        if sum(i['runs'] for i in p['inning_scores'] if i['batting_team_id'] == sid and i['was_played']) != score:
                            raise Refused('raw_inning_mismatch')
                for year, h in headers.items():
                    items = [(r['competition_id'], r['match_id'], r['record_sha256']) for r in matches if r['year'] == year]
                    if h['status'] == 'sealed' and (len(items), sha(canonical(items))) != (h['match_count'], h['ledger_sha256']):
                        raise Refused('raw_ledger_mismatch')
                    if h['status'] not in ('active', 'sealed'):
                        raise Refused('raw_year_status')
                if 'historical_competition_outcomes' in tables:
                    for r in con.execute('SELECT * FROM historical_competition_outcomes'):
                        p = json.loads(r['payload_json'])
                        h = headers.get(r['year'])
                        if (sha(r['payload_json']) != r['record_sha256']
                                or (p['year'], p['competition_id']) != (r['year'], r['competition_id'])
                                or h is None or h['status'] != 'sealed'
                                or p['source_year_ledger_sha256'] != h['ledger_sha256']):
                            raise Refused('raw_outcome_mismatch')
                        items = [[m['match_id'], m['record_sha256']] for m in matches
                                 if m['year'] == r['year'] and m['competition_id'] == r['competition_id']
                                 and json.loads(m['payload_json'])['stage_code'] == 'MAIN']
                        if (len(items) != p['main_match_count']
                                or sha(canonical(items)) != p['source_match_sha256']):
                            raise Refused('raw_outcome_source_mismatch')
            else:
                identities = {}
                for r in con.execute('SELECT * FROM career_player_identities'):
                    p = json.loads(r['identity_json'])
                    if sha(r['identity_json']) != r['identity_sha256'] or any(p[k] != r[k] for k in ('player_id', 'school_id', 'entry_year')):
                        raise Refused('raw_identity_mismatch')
                    identities[r['player_id']] = p
                for r in con.execute('SELECT * FROM career_school_rosters'):
                    p = json.loads(r['payload_json'])
                    if sha(r['payload_json']) != r['content_sha256'] or (p['reference_year'], p['school_id']) != (r['year'], r['school_id']):
                        raise Refused('raw_roster_mismatch')
                    for player in p['players']:
                        identity = {k: v for k, v in player.items() if k != 'academic_year'}
                        if identities.get(player['player_id']) != identity:
                            raise Refused('raw_roster_identity_mismatch')
    return result


def live_and_membership(root, source):
    """Independent checkpoint/SQL and all-year roster membership comparison."""
    live = json.loads((root / (source + '.json')).read_text(encoding='utf-8'))
    body = dict(live)
    checksum = body.pop('payload_checksum', None)
    if checksum != sha(canonical(body)):
        raise Refused('raw_checkpoint_checksum')
    with closing(ro(root / 'career_rosters.sqlite3')) as con:
        roster = {}
        for year, school, payload in con.execute('SELECT year,school_id,payload_json FROM career_school_rosters'):
            roster[(year, school)] = {p['player_id'] for p in json.loads(payload)['players']}
    with closing(ro(root / 'historical_matches.sqlite3')) as con:
        con.row_factory = sqlite3.Row
        records = {(r['year'], r['competition_id'], r['match_id']): json.loads(r['payload_json'])
                   for r in con.execute('SELECT * FROM historical_matches')}
        header = con.execute('SELECT metadata_json FROM career_years WHERE year=?', (live['year'],)).fetchone()
        if header is None or any(json.loads(header[0])[k] != live[k]
                                 for k in ('year', 'rng_seed', 'resolver_contract', 'plan_fingerprint')):
            raise Refused('raw_live_identity')
    current = {k: p for k, p in records.items() if k[0] == live['year']}
    checkpoint = {(live['year'], p['competition_id'], p['match_id']): p
                  for p in live['completed_match_results'].values()}
    if current.keys() != checkpoint.keys():
        raise Refused('raw_live_match_set')
    for key, record in current.items():
        p = checkpoint[key]
        for name in ('competition_id', 'match_id', 'match_date', 'date_source',
                     'team1_id', 'team2_id', 'team1_score', 'team2_score', 'score_source',
                     'winner_id', 'loser_id', 'stage_code', 'phase_code', 'round_no'):
            if record[name] != p[name]:
                raise Refused('raw_live_result')
        detail = p.get('ability_detail') or {}
        for name in ('inning_scores', 'team_stats', 'batter_stats', 'pitcher_stats'):
            if record[name] != detail.get(name):
                raise Refused('raw_live_full_a')
    for (year, _cid, _mid), p in records.items():
        for row in (p.get('batter_stats') or []) + (p.get('pitcher_stats') or []):
            if row['school_id'] not in (p['team1_id'], p['team2_id']) or row['player_id'] not in roster.get((year, row['school_id']), set()):
                raise Refused('raw_match_roster_membership')

