"""Isolated Windows reproduction; sequential stores, fresh outputs, owned Docker cleanup."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
OWNER = 'vector-benchmark'
IMAGES = {
    'qdrant': 'qdrant/qdrant:v1.20.1',
    'pgvector': 'pgvector/pgvector:0.8.7-pg17',
    'milvus': 'milvusdb/milvus:v3.0.6',
    'weaviate': 'cr.weaviate.io/semitechnologies/weaviate:1.40.5',
    'hnswlib': 'python:3.12.10-slim-bookworm',
}
PORTS = {'qdrant': 16386, 'pgvector': 15486, 'milvus': 19586, 'weaviate': 18086}

def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n', encoding='utf8')

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--n', type=int, default=1000)
    p.add_argument('--out', default='runs/proof')
    p.add_argument('--native-only', action='store_true')
    a = p.parse_args()
    if os.name != 'nt':
        p.error('This driver uses Windows virtual environments. Individual adapters are portable.')
    if not 70 <= a.n <= 20000:
        p.error('--n must be 70..20000 (at least five passages per book)')
    os.chdir(ROOT)
    out = Path(a.out).resolve()
    if not out.is_relative_to(ROOT) or out == ROOT:
        p.error('--out must be a new child directory of this checkout')
    out.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    env.update(UV_CACHE_DIR=str(ROOT/'.cache/uv'), UV_PYTHON_DOWNLOADS='never',
               PIP_CACHE_DIR=str(ROOT/'.cache/pip'), HF_HOME=str(ROOT/'.cache/huggingface'),
               FASTEMBED_CACHE_PATH=str(ROOT/'.cache/fastembed'),
               PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
    commands = []
    containers, volumes, new_images = [], [], []
    cleanup = []

    def run(label, cmd, timeout=1800, check=True):
        cmd = list(map(str, cmd))
        print('START', label, flush=True)
        started = time.perf_counter()
        r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True,
                           encoding='utf8', errors='replace', timeout=timeout)
        (out/(label+'.stdout')).write_text(r.stdout, encoding='utf8')
        (out/(label+'.stderr')).write_text(r.stderr, encoding='utf8')
        commands.append(dict(label=label, command=cmd, returncode=r.returncode,
                             elapsed_s=time.perf_counter()-started))
        write(out/'commands.json', commands)
        print('DONE', label, r.returncode, flush=True)
        if check and r.returncode:
            raise RuntimeError(f'{label} failed; see its stderr log')
        return r

    def python(group):
        return ROOT/('.venv-'+group)/'Scripts/python.exe'

    def wait_ready(kind, name):
        started = time.monotonic()
        while time.monotonic()-started < 240:
            if kind == 'pgvector':
                r = subprocess.run(['docker', 'exec', name, 'pg_isready', '-U', 'postgres'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                if r.returncode == 0:
                    return
            else:
                url = {'qdrant': f'http://127.0.0.1:{PORTS[kind]}/readyz',
                       'milvus': 'http://127.0.0.1:19086/healthz',
                       'weaviate': f'http://127.0.0.1:{PORTS[kind]}/v1/.well-known/ready'}[kind]
                try:
                    with urllib.request.urlopen(url, timeout=2) as r:
                        if r.status == 200:
                            return
                except Exception:
                    pass
            time.sleep(1)
        raise TimeoutError(f'{kind} did not become ready')

    def acquire_image(kind):
        image = IMAGES[kind]
        r = run(kind+'-image-before', ['docker','image','inspect',image], check=False)
        if r.returncode:
            # Record ownership before pull, so even a later failure can be cleaned.
            new_images.append(image)
            run(kind+'-pull', ['docker','pull',image])
        r = run(kind+'-image-version', ['docker','image','inspect',image])
        data=json.loads(r.stdout)[0]
        versions[kind]=dict(image=image, image_id=data['Id'], repo_digests=data.get('RepoDigests', []), size_bytes=data['Size'])
        write(out/'container-versions.json',versions)
        return image

    def start(kind, bind=False):
        image = acquire_image(kind)
        name = 'vector-benchmark-'+kind+('-bind' if bind else '')
        # Existing resources with the same name cause a hard failure, never deletion.
        exists=subprocess.run(['docker','container','inspect',name], capture_output=True)
        if exists.returncode == 0:
            raise FileExistsError('Container already exists: '+name)
        location={'qdrant':'/qdrant/storage','pgvector':'/var/lib/postgresql/data',
                  'milvus':'/var/lib/milvus','weaviate':'/var/lib/weaviate'}[kind]
        if bind:
            host=out/'qdrant-bind-storage';host.mkdir()
            mount=str(host)+':'+location
        else:
            volume=name+'-data'
            exists=subprocess.run(['docker','volume','inspect',volume], capture_output=True)
            if exists.returncode == 0:
                raise FileExistsError('Volume already exists: '+volume)
            run(kind+'-volume',['docker','volume','create','--label','owner='+OWNER,volume])
            volumes.append(volume);mount=volume+':'+location
        cmd=['docker','run','-d','--name',name,'--label','owner='+OWNER,
             '--cpus','2','--memory','4g' if kind=='milvus' else '2g','-v',mount]
        settings={
            'qdrant':['QDRANT__TELEMETRY_DISABLED=true'],
            'pgvector':['POSTGRES_HOST_AUTH_METHOD=trust'],
            'milvus':['ETCD_USE_EMBED=true','ETCD_DATA_DIR=/var/lib/milvus/etcd',
                      'ETCD_CONFIG_PATH=/milvus/configs/embedEtcd.yaml','COMMON_STORAGETYPE=local','DEPLOY_MODE=STANDALONE'],
            'weaviate':['AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED=true','PERSISTENCE_DATA_PATH=/var/lib/weaviate',
                        'CLUSTER_HOSTNAME=benchmark-node','DEFAULT_VECTORIZER_MODULE=none','ENABLE_MODULES=',
                        'DISABLE_TELEMETRY=true','GOMAXPROCS=2','AUTOSCHEMA_ENABLED=false','DEFAULT_QUANTIZATION=none'],
        }
        for setting in settings[kind]:
            cmd+=['-e',setting]
        port=PORTS[kind]
        if kind=='qdrant':cmd+=['-p',f'127.0.0.1:{port}:6333']
        elif kind=='pgvector':cmd+=['-p',f'127.0.0.1:{port}:5432']
        elif kind=='weaviate':cmd+=['-p',f'127.0.0.1:{port}:8080','-p',f'127.0.0.1:{port+1}:50051']
        else:
            etcd=out/'embedEtcd.yaml'
            etcd.write_text('listen-client-urls: http://0.0.0.0:2379\nadvertise-client-urls: http://0.0.0.0:2379\nquota-backend-bytes: 4294967296\nauto-compaction-mode: revision\nauto-compaction-retention: "1000"\n', encoding='utf8')
            cmd+=['--security-opt','seccomp:unconfined','-v',str(etcd)+':/milvus/configs/embedEtcd.yaml:ro',
                  '-p',f'127.0.0.1:{port}:19530','-p','127.0.0.1:19086:9091']
        extra={'qdrant':[],'pgvector':[],'milvus':['milvus','run','standalone'],
               'weaviate':['--host','0.0.0.0','--port','8080','--scheme','http']}[kind]
        containers.append(name)
        run(kind+('-bind' if bind else '')+'-start',cmd+[image]+extra)
        wait_ready(kind,name)
        return name

    def stop(name):
        run(name+'-logs',['docker','logs','--tail','80',name],check=False)
        r=run(name+'-remove',['docker','rm','-f',name],check=False)
        if r.returncode == 0:containers.remove(name)

    versions={}
    try:
        run('python-version',[sys.executable,'--version'])
        run('uv-version',['uv','--version'])
        for group in ['native','faiss','servers']:
            venv=ROOT/('.venv-'+group)
            if venv.exists():raise FileExistsError('Use a clean checkout: '+venv.name)
            run(group+'-venv',['uv','venv','--python',sys.executable,venv])
            run(group+'-install',['uv','pip','sync','--python',python(group),'requirements/'+group+'.lock'])
            run(group+'-pip-check',['uv','pip','check','--python',python(group)])
            run(group+'-versions',['uv','pip','freeze','--python',python(group)])
        # All downloads and embeddings are produced here, with no pre-existing data.
        run('prepare',[python('native'),'-X','utf8','-B','scripts/workload.py','prepare','--n',a.n])
        run('native',[python('native'),'-X','utf8','-B','scripts/workload.py','run','--n',a.n,'--out',out/'native'])
        run('faiss',[python('faiss'),'-X','utf8','-B','scripts/faiss_benchmark.py','--n',a.n,'--out',out/'faiss'])
        base=[python('servers'),'-X','utf8','-B','scripts/benchmark.py','--n',a.n]
        run('sqlite-vec',base+['--store','sqlite-vec','--out',out/'sqlite-vec'])
        run('sqlite-vec-reopen',base+['--store','sqlite-vec','--out',out/'sqlite-vec','--reopen'])
        if not a.native_only:
            run('docker-version',['docker','version','--format','{{.Server.Version}}'])
            for bind in [False,True]:
                name=start('qdrant',bind)
                target=out/('qdrant-bind' if bind else 'qdrant-named')
                cmd=[python('native'),'-X','utf8','-B','scripts/workload.py']
                run(target.name,cmd+['run','--n',a.n,'--out',target,'--stores','qdrant-server',
                                     '--server-url',f'http://127.0.0.1:{PORTS["qdrant"]}'])
                run(target.name+'-restart',['docker','restart',name]);wait_ready('qdrant',name)
                run(target.name+'-reopen',cmd+['reopen','--n',a.n,'--out',target,'--store','qdrant-server',
                                            '--server-url',f'http://127.0.0.1:{PORTS["qdrant"]}'])
                stop(name)
            for kind in ['pgvector','milvus','weaviate']:
                name=start(kind)
                cmd=base+['--store',kind,'--port',PORTS[kind],'--name','Literature' if kind=='weaviate' else 'literature','--out',out/kind]
                run(kind,cmd)
                run(kind+'-restart',['docker','restart',name]);wait_ready(kind,name)
                run(kind+'-reopen',cmd+['--reopen'])
                stop(name)
            image=acquire_image('hnswlib')
            name='vector-benchmark-hnswlib'
            exists=subprocess.run(['docker','container','inspect',name],capture_output=True)
            if exists.returncode==0:raise FileExistsError(name)
            containers.append(name)
            shell='apt-get update && apt-get install -y --no-install-recommends g++ && python -m pip install --no-cache-dir -r requirements/hnswlib.lock && python -B scripts/benchmark.py --store hnswlib --data data --out '+a.out+'/hnswlib --n '+str(a.n)+' && python -B scripts/benchmark.py --store hnswlib --data data --out '+a.out+'/hnswlib --n '+str(a.n)+' --reopen'
            # a.out is validated below; only a simple relative path enters the Linux shell.
            run('hnswlib',['docker','run','--name',name,'--label','owner='+OWNER,'--cpus','2','--memory','2g',
                           '-v',str(ROOT)+':/bench','-w','/bench',image,'sh','-c',shell])
            stop(name)
        run('verify',[sys.executable,'-B','scripts/verify_results.py','--run',out,'--n',a.n,
                      *(['--native-only'] if a.native_only else [])])
        write(out/'completed.json',dict(n=a.n,queries=300,stores=5 if a.native_only else 9,status='PASS'))
    finally:
        for name in list(containers):
            r=run(name+'-cleanup',['docker','rm','-f',name],check=False)
            cleanup.append(dict(type='container',name=name,returncode=r.returncode))
        for volume in volumes:
            r=run(volume+'-cleanup',['docker','volume','rm',volume],check=False)
            cleanup.append(dict(type='volume',name=volume,returncode=r.returncode))
        # Only images absent before this run are candidates. Never force shared image deletion.
        for image in dict.fromkeys(new_images):
            r=run(image.split('/')[-1].replace(':','-')+'-cleanup',['docker','image','rm',image],check=False)
            cleanup.append(dict(type='image',name=image,returncode=r.returncode))
        write(out/'docker-cleanup.json',cleanup)

if __name__=='__main__':
    # Disallow metacharacters before an output argument is interpolated into a container shell.
    import re
    values=sys.argv[1:]
    if '--out' in values and not re.fullmatch(r'[A-Za-z0-9_/-]+',values[values.index('--out')+1]):
        raise SystemExit('--out must be a simple relative path using letters, digits, _ - /')
    main()
