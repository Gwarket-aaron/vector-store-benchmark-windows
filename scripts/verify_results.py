"""Recalculate every stored latency percentile and exact-neighbor recall with stdlib."""
import argparse
import json
import math
from pathlib import Path

def load(p):return json.loads(p.read_text(encoding='utf8'))
def percentile(xs,q):
    xs=sorted(xs);i=(len(xs)-1)*q;lo=math.floor(i);hi=math.ceil(i)
    return xs[lo]+(xs[hi]-xs[lo])*(i-lo)
def verify(trials,refs,n):
    for key,t in trials.items():
        assert len(t['latencies_ms'])==len(t['ids'])==len(refs[key])==300
        assert math.isclose(percentile(t['latencies_ms'],.5),t['median_ms'],abs_tol=1e-9)
        assert math.isclose(percentile(t['latencies_ms'],.95),t['p95_ms'],abs_tol=1e-9)
        recall=sum(len(set(a)&set(b))/5 for a,b in zip(t['ids'],refs[key]))/300
        assert math.isclose(recall,t['recall_at_5'],abs_tol=1e-12)
        assert t['wrong_book_hits']==0
        assert all(len(ids)==len(set(ids))==5 and all(0<=i<n for i in ids) for ids in t['ids'])

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);p.add_argument('--n',type=int,required=True);p.add_argument('--native-only',action='store_true');a=p.parse_args()
    root=Path(a.run);checks=[]
    for folder,stores in [('native',['chroma','qdrant-local','lance'])]+([] if a.native_only else [('qdrant-named',['qdrant-server']),('qdrant-bind',['qdrant-server'])]):
        refs=load(root/folder/'exact.json')['references']
        for store in stores:
            r=load(root/folder/(store+'.json'));assert r['n']==a.n
            verify(r['trials'],refs,a.n)
            assert r['durable_reopen']['count']==a.n-1 and r['durable_reopen']['deleted_absent'] and r['durable_reopen']['updated_note']=='reviewed'
            checks.append(folder+'/'+store)
    r=load(root/'faiss/result.json');verify(r['trials'],load(root/'faiss/exact.json'),a.n);assert r['durable_reopen']['count']==a.n-1;checks.append('faiss')
    for kind in ['sqlite-vec']+([] if a.native_only else ['pgvector','milvus','weaviate','hnswlib']):
        r=load(root/kind/'result.json');refs=load(root/kind/'exact.json');assert r['n']==a.n
        for phase,data in r['phases'].items():verify(data['trials'],refs,a.n);checks.append(kind+'/'+phase)
        assert r['state']==dict(count=a.n-1,deleted_absent=True,updated_note='reviewed',book_id=135)
    result=dict(status='PASS',n=a.n,queries=300,configurations=len(checks),checks=checks)
    (root/'verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps(result))

if __name__=='__main__':main()
