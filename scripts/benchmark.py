"""Five store adapters using shared prepared arrays; exact references outside request timing."""
import argparse,hashlib,json,os,platform,sys,time,uuid
from pathlib import Path
for key in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS']:os.environ[key]='2'
os.environ.update(DO_NOT_TRACK='1',ANONYMIZED_TELEMETRY='False',OTEL_SDK_DISABLED='true')
import numpy as np
ROOT=Path(__file__).resolve().parent
DATA=Path('data')
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
class Store:
    def __init__(self,kind,path,name,port,create=False):
        self.kind,self.path,self.name,self.port=kind,path,name,port
        self.configuration={};self.db=None;self.c=None
        self.exact_filter=False
        if kind=='pgvector':
            import psycopg
            from pgvector.psycopg import register_vector
            self.db=psycopg.connect(host='127.0.0.1',port=port,user='postgres',dbname='postgres',autocommit=True)
            self.db.execute('CREATE EXTENSION IF NOT EXISTS vector');register_vector(self.db)
            if create:
                self.db.execute(f'CREATE TABLE {name} (id bigint PRIMARY KEY, text text NOT NULL, book_id bigint NOT NULL, note text NOT NULL, embedding vector(384))')
                self.db.execute(f'CREATE INDEX ON {name}(book_id)')
            self.db.execute("SET max_parallel_workers_per_gather=0")
            self.db.execute('SET hnsw.ef_search=100');self.db.execute("SET hnsw.iterative_scan='strict_order'")
            self.configuration={'postgres':self.db.execute('SHOW server_version').fetchone()[0],'extension':self.db.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()[0],'ef_search':100,'iterative_scan':'strict_order','query_planner':'default, max_parallel_workers_per_gather=0; actual EXPLAIN saved'}
        elif kind=='milvus':
            from pymilvus import MilvusClient,DataType
            self.db=MilvusClient(uri=f'http://127.0.0.1:{port}',timeout=120)
            if create:
                schema=self.db.create_schema(auto_id=False,enable_dynamic_field=False)
                for field,typ,kw in [('id',DataType.INT64,{'is_primary':True}),('text',DataType.VARCHAR,{'max_length':8192}),('book_id',DataType.INT64,{}),('note',DataType.VARCHAR,{'max_length':32}),('embedding',DataType.FLOAT_VECTOR,{'dim':384})]:schema.add_field(field_name=field,datatype=typ,**kw)
                self.db.create_collection(collection_name=name,schema=schema,consistency_level='Strong')
            self.configuration={'server':self.db.get_server_version(),'metric':'COSINE','index':'HNSW','M':16,'efConstruction':100,'ef':100,'consistency':'Strong'}
        elif kind=='weaviate':
            import weaviate
            from weaviate.classes.config import Configure,Property,DataType,VectorDistances
            self.db=weaviate.connect_to_local(host='127.0.0.1',port=port,grpc_port=port+1)
            if create:
                self.db.collections.create(name=name,properties=[Property(name='source_id',data_type=DataType.INT),Property(name='text',data_type=DataType.TEXT,index_searchable=False),Property(name='book_id',data_type=DataType.INT),Property(name='note',data_type=DataType.TEXT)],vector_config=Configure.Vectors.self_provided(vector_index_config=Configure.VectorIndex.hnsw(distance_metric=VectorDistances.COSINE,ef=100,ef_construction=100,max_connections=16,flat_search_cutoff=0)))
            self.c=self.db.collections.get(name)
            self.configuration={'server':self.db.get_meta()['version'],'collection':str(self.c.config.get()),'ef':100,'ef_construction':100,'max_connections':16,'flat_search_cutoff':0}
        elif kind=='sqlite-vec':
            import sqlite3,sqlite_vec
            self.db=sqlite3.connect(path/'library.sqlite');self.db.enable_load_extension(True);sqlite_vec.load(self.db);self.db.enable_load_extension(False)
            if create:self.db.execute('CREATE VIRTUAL TABLE chunks USING vec0(id INTEGER PRIMARY KEY, embedding float[384] distance_metric=cosine, book_id INTEGER, +text TEXT, +note TEXT)')
            self.configuration={'sqlite':sqlite3.sqlite_version,'extension':self.db.execute('SELECT vec_version()').fetchone()[0],'index':'vec0 exact cosine scan; book_id metadata constraint inside KNN; auxiliary text/note','journal_mode':self.db.execute('PRAGMA journal_mode').fetchone()[0]}
        elif kind=='hnswlib':
            import hnswlib
            self.c=hnswlib.Index(space='cosine',dim=384)
            if not create:
                self.c.load_index(str(path/'vectors.bin'));self.rows={int(k):v for k,v in json.loads((path/'documents.json').read_text(encoding='utf8')).items()}
            self.c.set_num_threads(2)
            if not create:self.c.set_ef(100)
            self.configuration={'index':'HNSW cosine','M':16,'ef_construction':100,'ef':100,'threads':2,'filtered_threads':1,'metadata':'Python dict + JSON sidecar; per-candidate Python filter callback'}
    def ingest(self,rows,v):
        k=self.kind;name=self.name
        if k=='hnswlib':self.rows={r['id']:r.copy() for r in rows};self.c.init_index(max_elements=len(rows),ef_construction=100,M=16,random_seed=100);self.c.set_ef(100)
        for j in range(0,len(rows),500):
            batch=rows[j:j+500];emb=v[j:j+500]
            if k=='pgvector':
                with self.db.cursor() as cur:
                    with cur.copy(f'COPY {name} (id,text,book_id,note,embedding) FROM STDIN') as copy:
                        for r,e in zip(batch,emb):copy.write_row((r['id'],r['text'],r['book_id'],r['note'],'['+','.join(map(str,e))+']'))
            elif k=='milvus':self.db.insert(collection_name=name,data=[{**{key:r[key] for key in ['id','text','book_id','note']},'embedding':e.tolist()} for r,e in zip(batch,emb)])
            elif k=='weaviate':
                from weaviate.classes.data import DataObject
                result=self.c.data.insert_many([DataObject(uuid=uuid.UUID(int=r['id']+1),properties={'source_id':r['id'],'text':r['text'],'book_id':r['book_id'],'note':r['note']},vector=e.tolist()) for r,e in zip(batch,emb)])
                assert not result.has_errors,result.errors
            elif k=='sqlite-vec':
                self.db.executemany('INSERT INTO chunks(id,embedding,book_id,text,note) VALUES (?,?,?,?,?)',[(r['id'],e.tobytes(),r['book_id'],r['text'],r['note']) for r,e in zip(batch,emb)]);self.db.commit()
            elif k=='hnswlib':self.c.add_items(emb,np.array([r['id'] for r in batch]))
        if k=='hnswlib':self.save()
        if k=='pgvector':self.db.execute(f'ANALYZE {name}')
    def index(self):
        if self.kind=='pgvector':self.db.execute(f'CREATE INDEX {self.name}_hnsw ON {self.name} USING hnsw (embedding vector_cosine_ops) WITH(m=16,ef_construction=100)');self.db.execute(f'ANALYZE {self.name}')
        elif self.kind=='milvus':
            self.db.flush(collection_name=self.name,timeout=120)
            ix=self.db.prepare_index_params();ix.add_index(field_name='embedding',index_type='HNSW',metric_type='COSINE',params={'M':16,'efConstruction':100})
            self.db.create_index(collection_name=self.name,index_params=ix,timeout=180);self.db.load_collection(collection_name=self.name,timeout=180)
            self.configuration['index_state']=self.db.describe_index(collection_name=self.name,index_name='embedding')
    def search(self,q,book=None):
        k=self.kind
        if k=='pgvector':
            if book is not None and self.exact_filter:
                return [dict(zip(['id','text','book_id','note'],x)) for x in self.db.execute(f'WITH eligible AS MATERIALIZED (SELECT id,text,book_id,note,embedding FROM {self.name} WHERE book_id=%s) SELECT id,text,book_id,note FROM eligible ORDER BY embedding <=> %s LIMIT 5',(book,q)).fetchall()]
            where='' if book is None else 'WHERE book_id=%s'
            args=(q,) if book is None else (book,q)
            return [dict(zip(['id','text','book_id','note'],x)) for x in self.db.execute(f'SELECT id,text,book_id,note FROM {self.name} {where} ORDER BY embedding <=> %s LIMIT 5',args).fetchall()]
        if k=='milvus':
            hits=self.db.search(collection_name=self.name,data=[q.tolist()],anns_field='embedding',limit=5,filter='' if book is None else f'book_id == {int(book)}',output_fields=['text','book_id','note'],search_params={'metric_type':'COSINE','params':{'ef':100}},consistency_level='Strong')[0]
            return [dict(id=int(h['id']),**h['entity']) for h in hits]
        if k=='weaviate':
            from weaviate.classes.query import Filter
            hits=self.c.query.near_vector(near_vector=q.tolist(),limit=5,filters=None if book is None else Filter.by_property('book_id').equal(book),return_properties=['source_id','text','book_id','note']).objects
            return [dict(id=h.properties['source_id'],**{key:h.properties[key] for key in ['text','book_id','note']}) for h in hits]
        if k=='sqlite-vec':
            where='' if book is None else 'AND book_id=?'
            args=(q.tobytes(),) if book is None else (q.tobytes(),book)
            return [dict(zip(['id','text','book_id','note'],x)) for x in self.db.execute(f'SELECT id,text,book_id,note FROM chunks WHERE embedding MATCH ? AND k=5 {where} ORDER BY distance',args)]
        labels,_=self.c.knn_query(q.reshape(1,-1),k=5,num_threads=2 if book is None else 1,filter=None if book is None else lambda i:self.rows[i]['book_id']==book)
        return [self.rows[int(i)].copy() for i in labels[0]]
    def save(self):
        self.c.save_index(str(self.path/'vectors.bin'));(self.path/'documents.json').write_text(json.dumps(self.rows,ensure_ascii=False),encoding='utf8')
    def maintenance(self,rows,v):
        k=self.kind
        if k=='pgvector':
            with self.db.transaction():self.db.execute(f"UPDATE {self.name} SET note='reviewed' WHERE id=1");self.db.execute(f'DELETE FROM {self.name} WHERE id=0')
        elif k=='milvus':
            r=rows[1];self.db.upsert(collection_name=self.name,data=[dict(id=1,text=r['text'],book_id=r['book_id'],note='reviewed',embedding=v[1].tolist())]);self.db.delete(collection_name=self.name,ids=[0]);self.db.flush(collection_name=self.name,timeout=120)
        elif k=='weaviate':self.c.data.update(uuid=uuid.UUID(int=2),properties={'note':'reviewed'});self.c.data.delete_by_id(uuid=uuid.UUID(int=1))
        elif k=='sqlite-vec':self.db.execute("UPDATE chunks SET note='reviewed' WHERE id=1");self.db.execute('DELETE FROM chunks WHERE id=0');self.db.commit()
        else:self.rows[1]['note']='reviewed';self.c.mark_deleted(0);del self.rows[0];self.save()
    def state(self):
        k=self.kind
        if k=='pgvector':n=self.db.execute(f'SELECT count(*) FROM {self.name}').fetchone()[0];found={r[0]:dict(book_id=r[1],note=r[2]) for r in self.db.execute(f'SELECT id,book_id,note FROM {self.name} WHERE id IN (0,1)')}
        elif k=='milvus':
            n=self.db.query(collection_name=self.name,filter='',output_fields=['count(*)'],consistency_level='Strong')[0]['count(*)'];found={r['id']:r for r in self.db.query(collection_name=self.name,filter='id in [0,1]',output_fields=['book_id','note'],consistency_level='Strong')}
        elif k=='weaviate':
            n=self.c.aggregate.over_all(total_count=True).total_count;found={}
            for i in [0,1]:
                r=self.c.query.fetch_object_by_id(uuid.UUID(int=i+1))
                if r:found[i]=r.properties
        elif k=='sqlite-vec':n=self.db.execute('SELECT count(*) FROM chunks').fetchone()[0];found={r[0]:dict(book_id=r[1],note=r[2]) for r in self.db.execute('SELECT id,book_id,note FROM chunks WHERE id IN (0,1)')}
        else:n=len(self.rows);found={i:self.rows[i] for i in [0,1] if i in self.rows}
        return dict(count=n,deleted_absent=0 not in found,updated_note=found.get(1,{}).get('note'),book_id=found.get(1,{}).get('book_id'))
    def plans(self,q,book):
        if self.kind!='pgvector':return None
        plans={key:self.db.execute(f'EXPLAIN (FORMAT JSON) SELECT id,text,book_id,note FROM {self.name} '+('' if b is None else 'WHERE book_id=%s ' )+'ORDER BY embedding <=> %s LIMIT 5',(q,) if b is None else (b,q)).fetchone()[0] for key,b in [('plain',None),('filtered',book)]}
        if self.exact_filter:plans['filtered']=self.db.execute(f'EXPLAIN (FORMAT JSON) WITH eligible AS MATERIALIZED (SELECT id,text,book_id,note,embedding FROM {self.name} WHERE book_id=%s) SELECT id,text,book_id,note FROM eligible ORDER BY embedding <=> %s LIMIT 5',(book,q)).fetchone()[0]
        return plans
    def close(self):
        if self.db is not None:self.db.close()
def main():
    global DATA
    p=argparse.ArgumentParser();p.add_argument('--store',required=True);p.add_argument('--out',required=True);p.add_argument('--data',default=str(DATA));p.add_argument('--n',type=int,default=20000);p.add_argument('--queries',type=int,default=300);p.add_argument('--port',type=int);p.add_argument('--name',default='literature');p.add_argument('--reopen',action='store_true');a=p.parse_args();out=Path(a.out).resolve();DATA=Path(a.data)
    if a.reopen:
        db=Store(a.store,out,a.name,a.port)
        if a.store=='milvus':db.db.load_collection(collection_name=a.name,timeout=120)
        started=time.monotonic()
        while True:
            try:state=db.state();break
            except Exception:
                if a.store!='milvus' or time.monotonic()-started>90:raise
                time.sleep(1)
        assert state==dict(count=a.n-1,deleted_absent=True,updated_note='reviewed',book_id=135),state
        rows=[json.loads(s) for s in (DATA/'chunks.jsonl').read_text(encoding='utf8').splitlines()][:a.n]
        vectors=np.load(DATA/'vectors.npy');probes=[]
        for source,book in [(0,None),(1,135),(14,2600)]:
            hits=db.search(vectors[source],book)
            assert len(hits)==5 and all(h['id']!=0 for h in hits)
            for h in hits:
                assert h['text']==rows[h['id']]['text'] and h['book_id']==rows[h['id']]['book_id']
                assert book is None or h['book_id']==book
            probes.append(dict(source=source,book_id=book,ids=[h['id'] for h in hits]))
        if a.store=='hnswlib':
            assert db.c.get_current_count()==a.n
            assert set(db.c.get_ids_list())==set(range(a.n))
            # The count includes tombstones; retrieval above tests live/deleted behavior.
            stored=db.c.get_items([1,14]);assert np.allclose(stored,vectors[[1,14]],atol=1e-6)
        db.close();print(json.dumps(dict(**state,reopened_queries=probes)));return
    out.mkdir(parents=True,exist_ok=False)
    rows=[json.loads(s) for s in (DATA/'chunks.jsonl').read_text(encoding='utf8').splitlines()][:a.n];v=np.load(DATA/'vectors.npy')[:a.n].copy();q=np.load(DATA/'query-vectors.npy')[:a.queries].copy();spec=json.loads((DATA/'queries.json').read_text(encoding='utf8'))[:a.queries]
    assert len(rows)==a.n and len(q)==a.queries
    assert min(sum(r['book_id']==s['book_id'] for r in rows) for s in spec)>=5
    db=Store(a.store,out,a.name,a.port,True)
    t=time.perf_counter();db.ingest(rows,v);ingest=time.perf_counter()-t
    exact={}
    for key,filtered in [('plain',False),('filtered',True)]:
        refs=[]
        for vector,s in zip(q,spec):
            allowed=np.array([i for i,r in enumerate(rows) if not filtered or r['book_id']==s['book_id']]);order=np.argsort(-(v[allowed]@vector),kind='stable')[:5];refs.append(allowed[order].tolist())
        exact[key]=refs
    phases={};index_s=0
    for phase in (['exact','hnsw','hnsw-exact-filter'] if a.store=='pgvector' else ['configured']):
        if phase not in ['exact','hnsw-exact-filter']:t=time.perf_counter();db.index();index_s=time.perf_counter()-t
        db.exact_filter=phase=='hnsw-exact-filter'
        for i in range(20):db.search(q[i%len(q)])
        trials={}
        for key,filtered in [('plain',False),('filtered',True)]:
            timings=[];ids=[]
            for vector,s in zip(q,spec):
                t=time.perf_counter();hits=db.search(vector,s['book_id'] if filtered else None);timings.append((time.perf_counter()-t)*1000)
                assert len(hits)==5,(key,s,len(hits));ids.append([int(h['id']) for h in hits])
                assert len(set(ids[-1]))==5
                for h in hits:
                    source=rows[int(h['id'])];assert h['text']==source['text'] and h['book_id']==source['book_id']
                    assert not filtered or h['book_id']==s['book_id']
            trials[key]=dict(median_ms=float(np.median(timings)),p95_ms=float(np.percentile(timings,95)),latencies_ms=timings,ids=ids,wrong_book_hits=0,recall_at_5=sum(len(set(x)&set(y))/5 for x,y in zip(ids,exact[key]))/len(q))
        phases[phase]={'trials':trials,'plans':db.plans(q[0],spec[0]['book_id']),'filter_mode':'MATERIALIZED book subset then exact cosine sort' if db.exact_filter else 'native/default query path'}
    t=time.perf_counter();db.maintenance(rows,v);maintenance=time.perf_counter()-t;state=db.state();assert state==dict(count=a.n-1,deleted_absent=True,updated_note='reviewed',book_id=135),state
    db.close()
    write(out/'exact.json',exact)
    write(out/'result.json',dict(store=a.store,n=a.n,queries=a.queries,ingest_s=ingest,index_s=index_s,phases=phases,maintenance_s=maintenance,state=state,configuration=db.configuration,inputs={f:sha(DATA/f) for f in ['chunks.jsonl','vectors.npy','queries.json','query-vectors.npy']},os=platform.platform(),python=sys.version,scope='single sequential run, 20 unfiltered warmups, 300 plain then 300 book-filtered requests; returned IDs + original text + metadata, no vectors; embedding and NumPy exact-reference work outside request timing'))
    print(json.dumps(dict(store=a.store,n=a.n,ingest_s=ingest,index_s=index_s,maintenance_s=maintenance,summary={phase:{k:{f:t[f] for f in ['median_ms','p95_ms','recall_at_5']} for k,t in data['trials'].items()} for phase,data in phases.items()})),flush=True)
if __name__=='__main__':main()
