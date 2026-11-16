"""Validate the published full-run archive without installing dependencies."""
import csv
import hashlib
import json
from pathlib import Path
from verify_results import verify

ROOT=Path(__file__).resolve().parent.parent/'results'
def load(p):return json.loads(p.read_text(encoding='utf8'))
reference=load(ROOT/'full/exact-reference.json')
refs=reference['references']
counts=reference['book_counts']
books=[b['book_id'] for b in load(ROOT.parent/'corpus/sources.json')]
id_books=[]
for pos in range(max(counts.values())):
    for book in books:
        if pos<counts[str(book)]:id_books.append(book)
assert len(id_books)==20000
checked=[]
for item in load(ROOT/'provenance.json'):
    path=ROOT/item['file'];assert hashlib.sha256(path.read_bytes()).hexdigest()==item['public_sha256'],item['file']
    r=load(path)
    if 'trials' in r:phases={'default':dict(trials=r['trials'])}
    elif 'phases' in r:phases=r['phases']
    else:continue
    assert r['n']==20000 and r['queries']==300
    for name,phase in phases.items():
        verify(phase['trials'],refs,20000)
        for i,ids in enumerate(phase['trials']['filtered']['ids']):
            expected=books[i%len(books)]
            assert all(id_books[k]==expected for k in ids),(item['file'],name,i)
        checked.append(item['file']+'/'+name)
combined=load(ROOT/'combined.json')
for row in combined['rows']:
    raw=load(ROOT/row['source'])
    if 'trials' in raw:assert row['trials']==raw['trials']
    else:assert any(row['trials']==p['trials'] for p in raw['phases'].values())
    assert row['ingest_s']==raw['ingest_s']
with (ROOT/'summary.csv').open(encoding='utf8',newline='') as f:summary=list(csv.DictReader(f))
assert len(summary)==len(combined['rows'])==13
for row,record in zip(combined['rows'],summary):
    assert record['deployment']==row['label']
    assert float(record['ingest_s'])==row['ingest_s']
    for prefix,key in [('plain','plain'),('filtered','filtered')]:
        for suffix,field in [('p50_ms','median_ms'),('p95_ms','p95_ms'),('recall_at_5','recall_at_5')]:
            assert float(record[prefix+'_'+suffix])==row['trials'][key][field]
print(json.dumps(dict(status='PASS',full_rows=13,raw_trial_groups=len(checked),provenance_files=len(load(ROOT/'provenance.json')),checks=['checksums','latency percentiles','exact-neighbor recall','book filters','combined table','CSV precision'])))
