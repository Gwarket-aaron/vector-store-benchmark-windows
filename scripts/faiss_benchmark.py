"""FAISS exact search with metadata, ID selectors, and persisted sidecars."""
import argparse,hashlib,json,os,platform,subprocess,sys,time,threading
from pathlib import Path
for key in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS']:os.environ[key]='2'
import faiss,numpy as np,psutil
faiss.omp_set_num_threads(2)
ROOT=Path(__file__).resolve().parent;DATA=Path('data')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
p=argparse.ArgumentParser();p.add_argument('--data',default='data');p.add_argument('--out',required=True);p.add_argument('--n',type=int,default=20000);p.add_argument('--reopen',action='store_true');a=p.parse_args();out=Path(a.out).resolve();DATA=Path(a.data)
if a.reopen:
    index=faiss.read_index(str(out/'vectors.faiss'));rows={r['id']:r for r in json.loads((out/'documents.json').read_text(encoding='utf8'))}
    assert index.ntotal==len(rows)==a.n-1 and 0 not in rows and rows[1]['note']=='reviewed'
    assert set(faiss.vector_to_array(index.id_map))==set(rows)
    assert rows[1]['book_id']==135
    print(json.dumps(dict(count=index.ntotal,deleted_absent=True,updated_note=rows[1]['note'],book_id=rows[1]['book_id'])))
    sys.exit(0)
out.mkdir(parents=True,exist_ok=False)
records=[json.loads(s) for s in (DATA/'chunks.jsonl').read_text(encoding='utf8').splitlines()][:a.n]
vectors=np.ascontiguousarray(np.load(DATA/'vectors.npy')[:a.n],dtype='float32');queries=np.ascontiguousarray(np.load(DATA/'query-vectors.npy'),dtype='float32');spec=json.loads((DATA/'queries.json').read_text(encoding='utf8'))
assert len(records)==a.n and len(queries)==len(spec)==300
index=faiss.IndexIDMap2(faiss.IndexFlatIP(384));rows={r['id']:r.copy() for r in records}
process=psutil.Process();baseline=process.memory_info().rss;peaks=[baseline];stop=threading.Event()
def sample():
    while not stop.wait(.02):peaks.append(process.memory_info().rss)
thread=threading.Thread(target=sample,daemon=True);thread.start()
def save():
    faiss.write_index(index,str(out/'vectors.faiss'))
    (out/'documents.json').write_text(json.dumps(list(rows.values()),ensure_ascii=False),encoding='utf8')
t=time.perf_counter()
for start in range(0,a.n,500):index.add_with_ids(vectors[start:start+500],np.array([r['id'] for r in records[start:start+500]],dtype='int64'))
save();ingest=time.perf_counter()-t
def search(q,book=None):
    query=q.reshape(1,-1)
    if book is None:scores,ids=index.search(query,5)
    else:
        allowed=np.array([i for i,r in rows.items() if r['book_id']==book],dtype='int64')
        selector=faiss.IDSelectorBatch(allowed)
        scores,ids=index.search(query,5,params=faiss.SearchParameters(sel=selector))
    return [dict(id=int(i),text=rows[int(i)]['text'],book_id=rows[int(i)]['book_id'],note=rows[int(i)]['note']) for i in ids[0] if i!=-1]
for i in range(20):search(queries[i])
trials={};exact={}
for filtered in [False,True]:
    latencies=[];hit_ids=[];reference=[];wrong=0
    for q,s in zip(queries,spec):
        t=time.perf_counter();hits=search(q,s['book_id'] if filtered else None);latencies.append((time.perf_counter()-t)*1000)
        assert len(hits)==5
        hit_ids.append([h['id'] for h in hits])
        for h in hits:
            assert h['text']==records[h['id']]['text'] and h['book_id']==records[h['id']]['book_id']
            if filtered and h['book_id']!=s['book_id']:wrong+=1
    # Exact NumPy reference is outside the request timing and follows all queries.
    for q,s in zip(queries,spec):
        allowed=np.array([i for i,r in enumerate(records) if not filtered or r['book_id']==s['book_id']])
        best=np.argsort(-(vectors[allowed]@q),kind='stable')[:5];reference.append(allowed[best].tolist())
    key='filtered' if filtered else 'plain';exact[key]=reference
    trials[key]=dict(median_ms=float(np.median(latencies)),p95_ms=float(np.percentile(latencies,95)),latencies_ms=latencies,ids=hit_ids,wrong_book_hits=wrong,recall_at_5=sum(len(set(x)&set(y))/5 for x,y in zip(hit_ids,reference))/len(queries))
before=sum(p.stat().st_size for p in out.glob('*') if p.is_file());t=time.perf_counter()
rows[1]['note']='reviewed';assert index.remove_ids(np.array([0],dtype='int64'))==1;del rows[0];save();maintenance=time.perf_counter()-t
command=[sys.executable,'-X','utf8','-B',str(Path(__file__).resolve()),'--data',str(DATA.resolve()),'--out',str(out),'--n',str(a.n),'--reopen']
r=subprocess.run(command,capture_output=True,text=True,encoding='utf8',timeout=60)
(out/'reopen.stdout').write_text(r.stdout,encoding='utf8');(out/'reopen.stderr').write_text(r.stderr,encoding='utf8');assert r.returncode==0,r.stderr
stop.set();thread.join()
write(out/'result.json',dict(store='faiss-flat-ip-idmap2',version=faiss.__version__,n=a.n,queries=len(queries),ingest_s=ingest,trials=trials,disk_before_maintenance_bytes=before,disk_after_exit_bytes=sum((out/f).stat().st_size for f in ['vectors.faiss','documents.json']),rss_baseline_bytes=baseline,rss_peak_bytes=max(peaks+[process.memory_info().rss]),maintenance_s=maintenance,durable_reopen=json.loads(r.stdout),configuration='IndexIDMap2(IndexFlatIP(384)), two OpenMP threads; shared normalized arrays reused unchanged; per-request Python book scan + IDSelectorBatch; metadata/text in Python dict, JSON sidecar persisted with index',ingestion_scope='500-vector add_with_ids batches + initial write_index + JSON documents write; empty index and input mapping created before timer; no fsync or transactional two-file commit',inputs={f:sha(DATA/f) for f in ['chunks.jsonl','queries.json','vectors.npy','query-vectors.npy']},hardware=dict(os=platform.platform(),python=sys.version,physical_cpus=psutil.cpu_count(logical=False),logical_cpus=psutil.cpu_count(),ram_bytes=psutil.virtual_memory().total)))
write(out/'exact.json',exact)
print(json.dumps({k:v for k,v in json.loads((out/'result.json').read_text(encoding='utf8')).items() if k in ['store','n','ingest_s','maintenance_s','durable_reopen']}))
