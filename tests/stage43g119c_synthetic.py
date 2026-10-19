"""Deterministic synthetic storage benchmark; NOT a real match runner/bracket.

31/64/128/256 records exceed real v3's 31-game scope only in this isolated
harness. Bytes digest is measured separately; full replay is a single pass.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from time import perf_counter, process_time


def run():
    measured=[]
    for size in (31,64,128,256):
        with tempfile.TemporaryDirectory(prefix='stage119c-synthetic-') as temp:
            path=Path(temp)/'synthetic-only.sqlite3'
            chain=hashlib.sha256(b'synthetic-only-genesis').hexdigest()
            genesis=chain
            with sqlite3.connect(path) as con:
                con.execute('PRAGMA journal_mode=DELETE')
                con.execute('PRAGMA synchronous=FULL')
                con.execute('CREATE TABLE synthetic (n INTEGER PRIMARY KEY, payload TEXT, sha TEXT, chain TEXT) STRICT')
                con.commit()
                games=[]; cpu=process_time()
                for n in range(size):
                    t=perf_counter()
                    payload=json.dumps(dict(sequence=n, synthetic=True, events=[(n*17+i)%97 for i in range(512)]),separators=(',',':'))
                    sha=hashlib.sha256(payload.encode()).hexdigest()
                    chain=hashlib.sha256((chain+sha).encode()).hexdigest()
                    derive=perf_counter()-t
                    t=perf_counter()
                    con.execute('BEGIN IMMEDIATE')
                    con.execute('INSERT INTO synthetic VALUES (?,?,?,?)',(n,payload,sha,chain)); con.commit()
                    transaction=perf_counter()-t
                    t=perf_counter()
                    with path.open('rb') as inp: digest=hashlib.file_digest(inp,'sha256').hexdigest()
                    games.append(dict(sequence=n+1,derive_seconds=derive,transaction_seconds=transaction,
                        db_digest_seconds=perf_counter()-t))
                t=perf_counter(); previous=genesis
                for n,payload,sha,expected in con.execute('SELECT * FROM synthetic ORDER BY n'):
                    assert hashlib.sha256(payload.encode()).hexdigest()==sha
                    previous=hashlib.sha256((previous+sha).encode()).hexdigest();assert expected==previous
                audit=perf_counter()-t
                measured.append(dict(synthetic=True,records=size,db_bytes=path.stat().st_size,
                    digest=digest,games=games,full_audit_seconds=audit,cpu_seconds=process_time()-cpu,
                    full_audit_records_visited=size,prefix_serializations=0))
    return dict(kind='deterministic synthetic storage harness; no match runner; no tournament beyond 32 teams',
                measurements=measured,complexity_contract='one current-record serialization per append; one linear full replay; file SHA grows with bytes')
