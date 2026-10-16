"""Explicit 2026 real-master selection; never changes a master or competition."""
from collections import Counter
import hashlib
from .paths import resolve_data_file
from .career_roster_archive import _digest, _json

COUNTS = {'19': 33, '20': 33, '22': 34}


def audit_selection(repo):
    sources = {r['source_id']: r for name in ('sources.csv', 'phase2_sources.csv')
               for r in repo._read(resolve_data_file(repo.data_dir, name))}
    areas = {r['area_id']: r for r in repo._read(resolve_data_file(repo.data_dir, 'competition_areas.csv'))}
    schemes = {r['scheme_id']: r for r in repo._read(resolve_data_file(repo.data_dir, 'area_schemes.csv'))}
    rows, all_programs, all_memberships = [], [], []
    for pref, count in COUNTS.items():
        ids = [sid for sid in sorted(repo.schools)
               if repo.team(sid).prefecture_code == pref and repo.team(sid).program_id][:count]
        if len(ids) != count:
            raise ValueError('master does not contain declared school count')
        for sid in ids:
            school = repo.schools[sid]
            programs = [r for r in repo.tables['baseball_programs.csv']
                        if r['school_id'] == sid and r['discipline'] == 'hardball' and r['reference_year'] == '2026']
            if len(programs) != 1 or school['school_status'] != 'active':
                raise ValueError('school/program ambiguity')
            program = programs[0]
            memberships = [r for r in repo.tables['school_area_memberships.csv']
                           if r['program_id'] == program['program_id'] and r['reference_year'] == '2026']
            if len(memberships) != 2 or len({r['scheme_id'] for r in memberships}) != 2:
                raise ValueError('branch/district registration differs')
            references = [school, program]
            for m in memberships:
                area, scheme = areas[m['area_id']], schemes[m['scheme_id']]
                if (area['scheme_id'] != m['scheme_id'] or int(area['prefecture_code']) != int(pref)
                        or int(scheme['prefecture_code']) != int(pref)):
                    raise ValueError('prefecture/area/scheme mismatch')
                references.extend((m, area, scheme))
            source_ids = sorted({r['primary_source_id'] for r in references})
            if any(s not in sources or not sources[s]['url'] for s in source_ids):
                raise ValueError('unresolved source reference')
            all_programs.append(program['program_id'])
            all_memberships.extend(m['membership_id'] for m in memberships)
            rows.append(dict(school_id=sid, program_id=program['program_id'], prefecture_code=pref,
                school_name=school['display_name'], memberships=memberships,
                sources=[sources[s] for s in source_ids]))
    if len(set(all_programs)) != 100 or len(set(all_memberships)) != 200:
        raise ValueError('cross-prefecture program/membership ID collision')
    files = {str(p.relative_to(repo.data_dir)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(repo.data_dir.rglob('*.csv'))}
    names = Counter(r['school_name'] for r in rows)
    return dict(counts=COUNTS, schools=rows, school_count=len(rows), program_count=len(set(all_programs)),
        membership_count=len(all_memberships), same_name_distinct_ids={
            name: [r['school_id'] for r in rows if r['school_name'] == name]
            for name, n in names.items() if n > 1},
        master_csv_bytes_sha256=files, audit_sha256=_digest(_json(rows)),
        scope='2026 school selection only; no tournament entries or 2027 authority')
