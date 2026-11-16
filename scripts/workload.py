"""Reproducible literature passage retrieval. No paid APIs. Python 3.12.

prepare: download original Gutenberg texts and a pinned public ONNX model, embed.
run: cached shared inputs, independent store processes, exact cosine reference.
worker/reopen are implementation commands used by run. Never overwrites a run.
"""
import argparse, hashlib, json, os, platform, re, subprocess, sys, time, traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','RAYON_NUM_THREADS'):
    os.environ[key]='2'
os.environ.update(DO_NOT_TRACK='1',ANONYMIZED_TELEMETRY='False',OTEL_SDK_DISABLED='true',TOKENIZERS_PARALLELISM='false',HF_HUB_DISABLE_TELEMETRY='1')
ROOT=Path(__file__).resolve().parent
BOOKS=[(2600,'War and Peace'),(135,'Les Miserables'),(1184,'The Count of Monte Cristo'),(2701,'Moby Dick'),(145,'Middlemarch'),(1400,'Great Expectations'),(1260,'Jane Eyre'),(1342,'Pride and Prejudice'),(11,'Alice in Wonderland'),(84,'Frankenstein'),(1661,'The Adventures of Sherlock Holmes'),(98,'A Tale of Two Cities'),(74,'Tom Sawyer'),(768,'Wuthering Heights')]
MODEL_BASE='https://huggingface.co/Qdrant/bge-small-en-v1.5-onnx-Q/resolve/aa8f8b060edb00e03bfdd08813a2949946c8ba55'
REV=MODEL_BASE.rsplit('/',1)[1]
MODEL_FILES=['README.md','config.json','model_optimized.onnx','ort_config.json','special_tokens_map.json','tokenizer.json','tokenizer_config.json','vocab.txt']
TOPICS=('a voyage at sea|a family inheritance|an unexpected visitor|a secret marriage|a military battle|a difficult moral choice|a debt that cannot be paid|a false accusation|a prison escape|a reunion after separation|a journey by carriage|a dangerous storm|an unhappy childhood|a promise of revenge|a confession of love|a deathbed conversation|a wealthy household|life in poverty|a political revolution|a ruined reputation|a trial in court|a missing person|a letter bearing bad news|a concealed identity|a conversation about religion|a conflict between generations|an act of forgiveness|a search for evidence|an illness and recovery|a wedding celebration|a funeral procession|a friendship betrayed|a life in exile|a change of fortune|a suspicious stranger|a dispute over money|a conversation about education|a long winter|a summer evening|a crowded city street|a country estate|a boarding school|a whale hunt|a broken engagement|a duel between rivals|a soldier returning home|a mother and child|a generous gift|a hidden document|a dream or nightmare|a desperate rescue|a lonely traveler|a moment of jealousy|a plan to deceive someone|a feeling of guilt|a courageous decision|a meal shared with guests|a garden conversation|a dangerous experiment|a detective investigating a crime|a train journey|a stolen object|a dispute between neighbors|a servant sharing information|a ship approaching land|a young person seeking work|an invitation to a ball|a disagreement about social class|a fear of death|a memory of home|a surprising discovery|a character reading a book|a disappointment in love|a visit to a hospital|a negotiation with an enemy|a lesson learned too late|a confrontation with authority|a musician performing|a change in the weather|a difficult return home|a character hiding the truth|a message sent in haste|a person losing hope|a kindness from a stranger|an argument about justice|a beautiful landscape|a dangerous animal|a child playing outside|a sleepless night|a family gathering|a public speech|a shop or marketplace|a fear of punishment|an escape from danger|a difficult apology|a character feeling ashamed|a journey across a border|a soldier receiving orders|a plan for the future|an unexpected ending').split('|')

def stamp():return datetime.now(timezone.utc).isoformat()
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,obj):Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf8')
def fetch(url,path):
    import urllib.request
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():return
    for attempt in range(3):
        try:
            request=urllib.request.Request(url,headers={'User-Agent':'Gwarket-vector-benchmark/1.0'})
            with urllib.request.urlopen(request,timeout=90) as r:body=r.read()
            path.write_bytes(body);return
        except Exception:
            if attempt==2:raise
            time.sleep(1+attempt)

def prepare(a):
    import numpy as np
    from fastembed import TextEmbedding
    data=Path(a.data).resolve();data.mkdir(parents=True,exist_ok=True)
    if (data/'preparation.json').exists():raise FileExistsError('Prepared data already exists; choose a new --data directory')
    raw=data/'raw'; model=data/'model';corpus=[];sources=[]
    for book_id,title in BOOKS:
        url=f'https://www.gutenberg.org/ebooks/{book_id}.txt.utf-8'
        p=raw/f'{book_id}.txt';fetch(url,p)
        expected=json.loads((ROOT.parent/'corpus/sources.json').read_text(encoding='utf8'))
        expected=next(b['sha256'] for b in expected if b['book_id']==book_id)
        if sha(p)!=expected:raise ValueError(f'Corpus source changed: book {book_id}. Save a new dated source record rather than mixing with the published run.')
        text=p.read_text(encoding='utf-8-sig')
        landing=raw/f'{book_id}.html';fetch(f'https://www.gutenberg.org/ebooks/{book_id}',landing)
        assert 'Public domain in the USA.' in landing.read_text(encoding='utf8'),f'Check rights record: {book_id}'
        start=re.search(r'\*\*\* START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK[^\n]*\n',text)
        end=re.search(r'\*\*\* END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK',text)
        assert start and end,book_id
        words=text[start.end():end.start()].split()
        chunks=[' '.join(words[i:i+96]) for i in range(0,len(words)-95,80)]
        corpus.append((book_id,title,chunks))
        sources.append(dict(book_id=book_id,title=title,url=url,landing=f'https://www.gutenberg.org/ebooks/{book_id}',sha256=sha(p),words=len(words),available_chunks=len(chunks),rights_header=text[:text.find('*** START')],retrieved=stamp()))
        print(f'downloaded {book_id}: {len(chunks)} chunks',flush=True)
    # Round robin preserves every book even in a reduced-size replay.
    rows=[]
    for j in range(max(len(x[2]) for x in corpus)):
        for book_id,title,chunks in corpus:
            if j<len(chunks):rows.append(dict(id=len(rows),book_id=book_id,title=title,word_start=j*80,text=chunks[j],note='original'))
            if len(rows)==a.n:break
        if len(rows)==a.n:break
    assert len(rows)==a.n,(len(rows),a.n)
    (data/'chunks.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf8')
    queries=[]
    for form in ['Find passages about {}.','Where does the story describe {}?','Retrieve a passage involving {}.']:
        for topic in TOPICS:queries.append(dict(id=len(queries),text=form.format(topic),book_id=BOOKS[len(queries)%len(BOOKS)][0]))
    assert len(queries)==300
    write(data/'queries.json',queries)
    expected_model=json.loads((ROOT.parent/'corpus/model.json').read_text(encoding='utf8'))['files']
    for f in MODEL_FILES:
        fetch(f'{MODEL_BASE}/{f}',model/f)
        if sha(model/f)!=expected_model[f]:raise ValueError(f'Model file hash mismatch: {f}')
    embedder=TextEmbedding(model_name='BAAI/bge-small-en-v1.5',cache_dir=str(data/'model-cache'),specific_model_path=str(model),local_files_only=True,threads=2,providers=['CPUExecutionProvider'])
    t=time.perf_counter();vectors=[]
    for j in range(0,len(rows),256):
        vectors.extend(embedder.passage_embed([r['text'] for r in rows[j:j+256]],batch_size=64))
        if j%2048==0:print(f'embedded {min(j+256,len(rows))}/{len(rows)}',flush=True)
    v=np.array(vectors,dtype='float32');passage_seconds=time.perf_counter()-t
    t=time.perf_counter();q=np.array(list(embedder.query_embed([r['text'] for r in queries],batch_size=64)),dtype='float32');query_seconds=time.perf_counter()-t
    v/=np.linalg.norm(v,axis=1,keepdims=True);q/=np.linalg.norm(q,axis=1,keepdims=True)
    assert v.shape==(a.n,384) and q.shape==(300,384) and np.isfinite(v).all()
    np.save(data/'vectors.npy',v);np.save(data/'query-vectors.npy',q)
    write(data/'preparation.json',dict(at=stamp(),books=sources,n=len(rows),dimensions=384,chunk_words=96,stride_words=80,book_counts=dict(Counter(r['book_id'] for r in rows)),query_provenance='100 explicit literary topics x 3 question forms; authored programmatically, not held-out relevance labels',model='BAAI/bge-small-en-v1.5',model_revision=REV,model_files={f:sha(model/f) for f in MODEL_FILES},passage_embedding_s=passage_seconds,query_embedding_s=query_seconds,files={f:sha(data/f) for f in ['chunks.jsonl','queries.json','vectors.npy','query-vectors.npy']}))
    print('PREPARED',passage_seconds,flush=True)

def load(a):
    import numpy as np
    data=Path(a.data)
    rows=[json.loads(s) for s in (data/'chunks.jsonl').read_text(encoding='utf8').splitlines()][:a.n]
    v=np.load(data/'vectors.npy')[:a.n].copy();q=np.load(data/'query-vectors.npy')[:a.queries].copy()
    queries=json.loads((data/'queries.json').read_text(encoding='utf8'))[:a.queries]
    assert len(rows)==a.n and len(q)==a.queries and len(queries)==a.queries,'Requested sample exceeds prepared data'
    assert all(sum(r['book_id']==book for r in rows)>=5 for book in {x['book_id'] for x in queries}),'Each queried book needs at least 5 chunks'
    return rows,v,q,queries

def connect(store,path,create=False,url=None):
    if store=='chroma':
        import chromadb
        from chromadb.config import Settings
        db=chromadb.PersistentClient(path=str(path),settings=Settings(anonymized_telemetry=False))
        c=db.create_collection('literature',embedding_function=None,configuration={'hnsw':{'space':'cosine','ef_search':100,'num_threads':2}}) if create else db.get_collection('literature',embedding_function=None)
        return db,c
    if store.startswith('qdrant'):
        from qdrant_client import QdrantClient,models
        db=QdrantClient(url=url,timeout=120) if store=='qdrant-server' else QdrantClient(path=str(path))
        if create:
            options={'optimizers_config':models.OptimizersConfigDiff(default_segment_number=1,indexing_threshold=1000),'hnsw_config':models.HnswConfigDiff(m=16,ef_construct=100,full_scan_threshold=1000)} if store=='qdrant-server' else {}
            db.create_collection('literature',vectors_config=models.VectorParams(size=384,distance=models.Distance.COSINE),**options)
            if store=='qdrant-server':db.create_payload_index('literature','book_id',models.PayloadSchemaType.INTEGER,wait=True)
        return db,None
    if store=='lance':
        import lancedb,pyarrow as pa
        db=lancedb.connect(str(path))
        schema=pa.schema([('id',pa.int64()),('text',pa.string()),('book_id',pa.int64()),('note',pa.string()),('vector',pa.list_(pa.float32(),384))])
        return db,db.create_table('literature',schema=schema) if create else db.open_table('literature')
    raise ValueError(store)

def search(store,db,c,vector,book_id=None):
    vector=vector.tolist()
    if store=='chroma':
        kw={'where':{'book_id':book_id}} if book_id is not None else {}
        r=c.query(query_embeddings=[vector],n_results=5,include=['documents','metadatas'],**kw)
        return [dict(id=int(i),text=t,book_id=m['book_id'],note=m['note']) for i,t,m in zip(r['ids'][0],r['documents'][0],r['metadatas'][0])]
    if store.startswith('qdrant'):
        from qdrant_client import models
        f=models.Filter(must=[models.FieldCondition(key='book_id',match=models.MatchValue(value=book_id))]) if book_id is not None else None
        hits=db.query_points('literature',query=vector,query_filter=f,limit=5,with_payload=True,with_vectors=False,search_params=models.SearchParams(hnsw_ef=100)).points
        return [dict(id=p.id,**p.payload) for p in hits]
    query=c.search(vector).distance_type('cosine').select(['id','text','book_id','note']).limit(5)
    if book_id is not None:query=query.where(f'book_id = {int(book_id)}',prefilter=True)
    return query.to_list()

def count(store,db,c):
    return c.count() if store=='chroma' else db.count('literature',exact=True).count if store.startswith('qdrant') else c.count_rows()

def disk(path):return sum(p.stat().st_size for p in Path(path).rglob('*') if p.is_file())

def worker(a):
    import numpy as np,psutil,threading
    rows,v,q,queries=load(a);out=Path(a.out);dbpath=Path(a.server_storage) if a.store=='qdrant-server' and a.server_storage else out/a.store
    # Import/connect before baseline: baseline includes empty store and input arrays.
    db,c=connect(a.store,dbpath,True,a.server_url)
    process=psutil.Process();baseline=process.memory_info().rss;peaks=[baseline];stop=threading.Event()
    def sample():
        while not stop.wait(.02):peaks.append(process.memory_info().rss)
    sampler=threading.Thread(target=sample,daemon=True);sampler.start()
    t=time.perf_counter()
    for j in range(0,len(rows),500):
        batch=rows[j:j+500];emb=v[j:j+500]
        if a.store=='chroma':
            c.add(ids=[str(r['id']) for r in batch],embeddings=emb,documents=[r['text'] for r in batch],metadatas=[dict(book_id=r['book_id'],note=r['note']) for r in batch])
        elif a.store.startswith('qdrant'):
            from qdrant_client import models
            db.upsert('literature',points=[models.PointStruct(id=r['id'],vector=e.tolist(),payload=dict(text=r['text'],book_id=r['book_id'],note=r['note'])) for r,e in zip(batch,emb)],wait=True)
        else:
            import pyarrow as pa
            schema=pa.schema([('id',pa.int64()),('text',pa.string()),('book_id',pa.int64()),('note',pa.string()),('vector',pa.list_(pa.float32(),384))])
            table=pa.Table.from_pylist([dict(id=r['id'],text=r['text'],book_id=r['book_id'],note=r['note'],vector=e.tolist()) for r,e in zip(batch,emb)],schema=schema)
            c.add(table)
    ingest=time.perf_counter()-t
    assert count(a.store,db,c)==len(rows)
    index_wait=0;index_state=None
    if a.store=='qdrant-server':
        t=time.perf_counter();previous=None;stable=0
        while True:
            state=db.get_collection('literature');index_state=state.model_dump(mode='json')
            signature=(state.indexed_vectors_count,state.segments_count)
            stable=stable+1 if signature==previous else 0;previous=signature
            enough=state.indexed_vectors_count>=.9*len(rows) if len(rows)>=2000 else True
            if state.status.value=='green' and state.optimizer_status=='ok' and stable>=4 and enough:break
            if time.perf_counter()-t>180:raise TimeoutError('Qdrant optimizer did not settle')
            time.sleep(.5)
        index_wait=time.perf_counter()-t
    # Warm caches with 20 calls, then retain every latency and returned ID.
    for i in range(20):search(a.store,db,c,q[i%len(q)])
    trials={}
    for filtered in [False,True]:
        timings=[];ids=[];bad=0
        for vector,query in zip(q,queries):
            t=time.perf_counter();hits=search(a.store,db,c,vector,query['book_id'] if filtered else None);timings.append((time.perf_counter()-t)*1000)
            assert len(hits)==5
            ids.append([int(h['id']) for h in hits])
            for hit in hits:
                original=rows[int(hit['id'])]
                assert hit['text']==original['text'] and hit['book_id']==original['book_id']
                if filtered and hit['book_id']!=query['book_id']:bad+=1
        trials['filtered' if filtered else 'plain']=dict(median_ms=float(np.median(timings)),p95_ms=float(np.percentile(timings,95)),latencies_ms=timings,ids=ids,wrong_book_hits=bad)
    before=disk(dbpath)
    t=time.perf_counter()
    if a.store=='chroma':c.update(ids=['1'],metadatas=[{'note':'reviewed'}]);c.delete(ids=['0'])
    elif a.store.startswith('qdrant'):
        from qdrant_client import models
        db.set_payload('literature',payload={'note':'reviewed'},points=[1],wait=True)
        db.delete('literature',models.PointIdsList(points=[0]),wait=True)
    else:c.update(where='id = 1',values={'note':'reviewed'});c.delete('id = 0')
    maintenance=time.perf_counter()-t
    assert count(a.store,db,c)==len(rows)-1
    # Probe overlapping access from another process, separate from durable reopen.
    command=[sys.executable,str(Path(__file__).resolve()),'reopen','--store',a.store,'--data',str(Path(a.data).resolve()),'--out',str(out),'--n',str(a.n)]
    if a.server_url:command+=['--server-url',a.server_url]
    concurrent=subprocess.run(command,capture_output=True,text=True,encoding='utf8',errors='replace',timeout=90)
    (out/f'{a.store}.concurrent.stdout').write_text(concurrent.stdout,encoding='utf8');(out/f'{a.store}.concurrent.stderr').write_text(concurrent.stderr,encoding='utf8')
    if a.store.startswith('qdrant'):db.close()
    stop.set();sampler.join();peak=max(peaks+[process.memory_info().rss])
    result=dict(store=a.store,at=stamp(),n=len(rows),queries=len(q),ingest_s=ingest,index_wait_s=index_wait,index_state=index_state,trials=trials,disk_before_maintenance_bytes=before,maintenance_s=maintenance,rss_baseline_bytes=baseline,rss_peak_bytes=peak,rss_sample_interval_s=.02,concurrent_open_exit=concurrent.returncode,concurrent_open_stdout=concurrent.stdout,concurrent_open_stderr=concurrent.stderr)
    write(out/f'{a.store}.json',result);print(json.dumps({k:result[k] for k in ['store','n','ingest_s','rss_peak_bytes','concurrent_open_exit']}),flush=True)

def reopen(a):
    db,c=connect(a.store,Path(a.out)/a.store,False,a.server_url)
    n=count(a.store,db,c)
    if a.store=='chroma':r=c.get(ids=['0','1']);found={int(i):m for i,m in zip(r['ids'],r['metadatas'])}
    elif a.store.startswith('qdrant'):found={int(p.id):p.payload for p in db.retrieve('literature',ids=[0,1],with_payload=True)}
    else:found={int(r['id']):r for r in c.to_arrow().filter(__import__('pyarrow').compute.field('id').isin([0,1])).to_pylist()}
    assert n==a.n-1,(n,a.n)
    assert 0 not in found and found[1]['note']=='reviewed',found
    rows=[json.loads(s) for s in (Path(a.data)/'chunks.jsonl').read_text(encoding='utf8').splitlines()]
    assert found[1]['book_id']==rows[1]['book_id'],'Partial metadata update lost book_id'
    if a.store.startswith('qdrant'):db.close()
    print(json.dumps(dict(count=n,deleted_absent=True,updated_note=found[1]['note'])))

def run(a):
    import numpy as np,psutil
    rows,v,q,queries=load(a);out=Path(a.out).resolve();out.mkdir(parents=True,exist_ok=False)
    write(out/'hardware.json',dict(at=stamp(),os=platform.platform(),python=sys.version,processor=platform.processor(),logical_cpus=os.cpu_count(),physical_cpus=psutil.cpu_count(logical=False),ram_bytes=psutil.virtual_memory().total,thread_env={k:os.environ[k] for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','RAYON_NUM_THREADS']},free_ram_at_start=psutil.virtual_memory().available))
    exact={};book_ids=np.array([r['book_id'] for r in rows]);t=time.perf_counter()
    for filtered in [False,True]:
        reference=[]
        for vec,query in zip(q,queries):
            indexes=np.where(book_ids==query['book_id'])[0] if filtered else np.arange(len(rows))
            scores=v[indexes]@vec;best=np.argsort(-scores,kind='stable')[:5];reference.append(indexes[best].tolist())
        exact['filtered' if filtered else 'plain']=reference
    write(out/'exact.json',dict(references=exact,seconds=time.perf_counter()-t,book_counts=dict(Counter(r['book_id'] for r in rows)),inputs={f:sha(Path(a.data)/f) for f in ['chunks.jsonl','queries.json','vectors.npy','query-vectors.npy']},n=a.n,queries=a.queries))
    summary=[]
    for store in a.stores.split(','):
        cmd=[sys.executable,str(Path(__file__).resolve()),'worker','--store',store,'--data',str(Path(a.data).resolve()),'--out',str(out),'--n',str(a.n),'--queries',str(a.queries)]
        if a.server_url:cmd+=['--server-url',a.server_url]
        if a.server_storage:cmd+=['--server-storage',a.server_storage]
        print('RUNNING',store,flush=True)
        p=subprocess.run(cmd,capture_output=True,text=True,encoding='utf8',errors='replace',timeout=1800)
        (out/f'{store}.stdout').write_text(p.stdout,encoding='utf8');(out/f'{store}.stderr').write_text(p.stderr,encoding='utf8')
        if p.returncode:raise RuntimeError(f'{store} failed, see {out}/{store}.stderr')
        result=json.loads((out/f'{store}.json').read_text(encoding='utf8'))
        for key,trial in result['trials'].items():trial['recall_at_5']=sum(len(set(x)&set(y))/5 for x,y in zip(trial['ids'],exact[key]))/len(q)
        cmd[2]='reopen'
        reopened=subprocess.run(cmd,capture_output=True,text=True,encoding='utf8',errors='replace',timeout=90)
        (out/f'{store}.reopen.stdout').write_text(reopened.stdout,encoding='utf8');(out/f'{store}.reopen.stderr').write_text(reopened.stderr,encoding='utf8')
        assert reopened.returncode==0,reopened.stderr
        result['durable_reopen']=json.loads(reopened.stdout.strip().splitlines()[-1]);result['disk_after_exit_bytes']=disk(Path(a.server_storage) if store=='qdrant-server' and a.server_storage else out/store)
        write(out/f'{store}.json',result);summary.append(result)
        write(out/'summary.json',summary)
        print('DONE',store,{key:dict(median_ms=trial['median_ms'],p95_ms=trial['p95_ms'],recall=trial['recall_at_5']) for key,trial in result['trials'].items()},flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','run','worker','reopen']);p.add_argument('--data',default='data');p.add_argument('--out',default='runs/native');p.add_argument('--n',type=int,default=20000);p.add_argument('--queries',type=int,default=300);p.add_argument('--stores',default='chroma,qdrant-local,lance');p.add_argument('--store',default='chroma');p.add_argument('--server-url');p.add_argument('--server-storage')
    args=p.parse_args()
    try:globals()[args.action](args)
    except Exception:traceback.print_exc();sys.exit(1)
