# Reproducing the workload

Run from a fresh checkout on 64-bit Windows with Python 3.12.10, `uv`, and Docker Desktop in Linux-container mode. The PowerShell driver is the tested entry point. It does not install global packages or register services. Three environment locks preserve the different grpc/protobuf versions used by the original runs. `requirements/hnswlib.lock` is used inside a Linux container.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\reproduce.ps1 -Size 1000 -Output runs/proof
```

For 20,000 passages use `-Size 20000` and a fresh clone. The 1,000-passage run verifies functionality; it should not be compared numerically with the 20,000-passage table. A small collection may never cross an approximate-index threshold. The raw Qdrant index state and PostgreSQL EXPLAIN plans make that visible.

The driver logs every command and return code to `runs/proof/commands.json`, captures stdout/stderr, and saves the server image IDs/digests in `container-versions.json`. Endpoints bind to loopback. PostgreSQL trust authentication and Weaviate anonymous access are for these disposable local containers. Do not use these settings on a public server.

## Preparation and individual Windows commands

These are the same preparation/adapter commands used by the driver. All commands below assume the repository root. Set caches inside it before using `uv`:

```powershell
$env:UV_CACHE_DIR = Join-Path $PWD '.cache/uv'
$env:UV_PYTHON_DOWNLOADS = 'never'
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
uv venv --python 3.12.10 .venv-native
uv pip sync --python .venv-native/Scripts/python.exe requirements/native.lock
uv venv --python 3.12.10 .venv-faiss
uv pip sync --python .venv-faiss/Scripts/python.exe requirements/faiss.lock
uv venv --python 3.12.10 .venv-servers
uv pip sync --python .venv-servers/Scripts/python.exe requirements/servers.lock
.venv-native/Scripts/python.exe -X utf8 -B scripts/workload.py prepare --data data --n 1000
.venv-native/Scripts/python.exe -X utf8 -B scripts/workload.py run --data data --out runs/native --n 1000 --queries 300 --stores chroma,qdrant-local,lance
.venv-faiss/Scripts/python.exe -X utf8 -B scripts/faiss_benchmark.py --data data --out runs/faiss --n 1000
.venv-servers/Scripts/python.exe -X utf8 -B scripts/benchmark.py --store sqlite-vec --data data --out runs/sqlite-vec --n 1000
.venv-servers/Scripts/python.exe -X utf8 -B scripts/benchmark.py --store sqlite-vec --data data --out runs/sqlite-vec --n 1000 --reopen
```

`prepare` downloads 14 original texts and their rights pages, verifies their recorded SHA-256 checksums, chunks round robin, downloads eight pinned model files, validates their checksums, computes 1,000 document and 300 query embeddings, normalizes them and writes NumPy arrays. Each prepared directory is write-once. A changed upstream book raises `Corpus source changed`; save a new dated source snapshot to investigate instead of disabling that check and treating it as the original workload.

## Docker configurations and exact commands

The tested driver expands these commands and records the resolved commands in its output. Its containers are named `vector-benchmark-*` with an ownership label and use a new named volume per server. If a container or volume with that name exists, it stops instead of touching it. Run stores sequentially to limit RAM use. The driver also repeats Qdrant with a Windows bind mount to retain the originally observed filesystem warning as a separate configuration.

```powershell
docker volume create --label owner=vector-benchmark vector-benchmark-qdrant-data
docker run -d --name vector-benchmark-qdrant --label owner=vector-benchmark --cpus 2 --memory 2g -e QDRANT__TELEMETRY_DISABLED=true -p 127.0.0.1:16386:6333 -v vector-benchmark-qdrant-data:/qdrant/storage qdrant/qdrant:v1.20.1
# Wait for http://127.0.0.1:16386/readyz before running:
.venv-native/Scripts/python.exe -X utf8 -B scripts/workload.py run --data data --out runs/qdrant-named --n 1000 --stores qdrant-server --server-url http://127.0.0.1:16386
docker restart vector-benchmark-qdrant
# Wait for readyz again:
.venv-native/Scripts/python.exe -X utf8 -B scripts/workload.py reopen --data data --out runs/qdrant-named --n 1000 --store qdrant-server --server-url http://127.0.0.1:16386
docker rm -f vector-benchmark-qdrant
docker volume rm vector-benchmark-qdrant-data

docker volume create --label owner=vector-benchmark vector-benchmark-pgvector-data
docker run -d --name vector-benchmark-pgvector --label owner=vector-benchmark --cpus 2 --memory 2g -e POSTGRES_HOST_AUTH_METHOD=trust -p 127.0.0.1:15486:5432 -v vector-benchmark-pgvector-data:/var/lib/postgresql/data pgvector/pgvector:0.8.7-pg17
# Wait for: docker exec vector-benchmark-pgvector pg_isready -U postgres
.venv-servers/Scripts/python.exe -X utf8 -B scripts/benchmark.py --store pgvector --data data --out runs/pgvector --n 1000 --port 15486 --name literature
docker restart vector-benchmark-pgvector
# Wait for pg_isready again, then:
.venv-servers/Scripts/python.exe -X utf8 -B scripts/benchmark.py --store pgvector --data data --out runs/pgvector --n 1000 --port 15486 --name literature --reopen
docker rm -f vector-benchmark-pgvector
docker volume rm vector-benchmark-pgvector-data

docker volume create --label owner=vector-benchmark vector-benchmark-weaviate-data
docker run -d --name vector-benchmark-weaviate --label owner=vector-benchmark --cpus 2 --memory 2g -e AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED=true -e PERSISTENCE_DATA_PATH=/var/lib/weaviate -e CLUSTER_HOSTNAME=benchmark-node -e DEFAULT_VECTORIZER_MODULE=none -e ENABLE_MODULES= -e DISABLE_TELEMETRY=true -e GOMAXPROCS=2 -e AUTOSCHEMA_ENABLED=false -e DEFAULT_QUANTIZATION=none -p 127.0.0.1:18086:8080 -p 127.0.0.1:18087:50051 -v vector-benchmark-weaviate-data:/var/lib/weaviate cr.weaviate.io/semitechnologies/weaviate:1.40.5 --host 0.0.0.0 --port 8080 --scheme http
# Wait for http://127.0.0.1:18086/v1/.well-known/ready
.venv-servers/Scripts/python.exe -X utf8 -B scripts/benchmark.py --store weaviate --data data --out runs/weaviate --n 1000 --port 18086 --name Literature
docker restart vector-benchmark-weaviate
# Wait for readiness, then repeat with --reopen:
.venv-servers/Scripts/python.exe -X utf8 -B scripts/benchmark.py --store weaviate --data data --out runs/weaviate --n 1000 --port 18086 --name Literature --reopen
docker rm -f vector-benchmark-weaviate
docker volume rm vector-benchmark-weaviate-data
```

Milvus uses embedded etcd and local object storage, so no separate etcd/MinIO services are needed. Write this configuration in the checkout, then mount it read-only:

```powershell
New-Item -ItemType Directory -Force runs | Out-Null
@'
listen-client-urls: http://0.0.0.0:2379
advertise-client-urls: http://0.0.0.0:2379
quota-backend-bytes: 4294967296
auto-compaction-mode: revision
auto-compaction-retention: "1000"
'@ | Set-Content -Encoding ASCII runs/embedEtcd.yaml
docker volume create --label owner=vector-benchmark vector-benchmark-milvus-data
$etcd = (Resolve-Path runs/embedEtcd.yaml).Path
docker run -d --name vector-benchmark-milvus --label owner=vector-benchmark --cpus 2 --memory 4g --security-opt seccomp:unconfined -e ETCD_USE_EMBED=true -e ETCD_DATA_DIR=/var/lib/milvus/etcd -e ETCD_CONFIG_PATH=/milvus/configs/embedEtcd.yaml -e COMMON_STORAGETYPE=local -e DEPLOY_MODE=STANDALONE -v vector-benchmark-milvus-data:/var/lib/milvus -v "${etcd}:/milvus/configs/embedEtcd.yaml:ro" -p 127.0.0.1:19586:19530 -p 127.0.0.1:19086:9091 milvusdb/milvus:v3.0.6 milvus run standalone
# Wait for http://127.0.0.1:19086/healthz
.venv-servers/Scripts/python.exe -X utf8 -B scripts/benchmark.py --store milvus --data data --out runs/milvus --n 1000 --port 19586 --name literature
docker restart vector-benchmark-milvus
# The adapter retries collection readiness after the health endpoint is available:
.venv-servers/Scripts/python.exe -X utf8 -B scripts/benchmark.py --store milvus --data data --out runs/milvus --n 1000 --port 19586 --name literature --reopen
docker rm -f vector-benchmark-milvus
docker volume rm vector-benchmark-milvus-data
```

hnswlib 0.8.0 is compiled in a disposable Linux Python container. The Windows host needs no compiler. Requirements are pinned in `requirements/hnswlib.lock`:

```powershell
docker run --name vector-benchmark-hnswlib --label owner=vector-benchmark --cpus 2 --memory 2g -v "${PWD}:/bench" -w /bench python:3.12.10-slim-bookworm sh -c 'apt-get update && apt-get install -y --no-install-recommends g++ && python -m pip install --no-cache-dir -r requirements/hnswlib.lock && python -B scripts/benchmark.py --store hnswlib --data data --out runs/hnswlib --n 1000 && python -B scripts/benchmark.py --store hnswlib --data data --out runs/hnswlib --n 1000 --reopen'
docker rm -f vector-benchmark-hnswlib
```

## Verification and cleanup

The driver checks IDs, original text and filters while querying, updates ID 1's note, deletes ID 0, and expects 999 records after reopening a 1,000-passage run. The verifier independently recomputes median/p95 from all 300 timings and recall from returned IDs against the saved exact references. Run it again without any installed dependencies:

```powershell
py -3.12 -B scripts/verify_results.py --run runs/proof --n 1000
```

Keep result JSON, exact references, command logs, preparation/model checksums and requirement locks. Do not commit the downloaded corpus/model, database directories or sidecars containing full text. To remove all generated files in this checkout after copying any results you want to keep:

```powershell
py -3.12 -B scripts/cleanup.py
```

Cleanup validates that targets are fixed child directories of the checkout. It removes only `.venv-native`, `.venv-faiss`, `.venv-servers`, `.cache`, `data` and `runs`. It does not prune Docker globally. The main driver already removes Docker resources it created and records return codes; if interrupted, inspect the ownership labels and `docker-cleanup.json` before removing named resources. Manually executed Docker commands above require their shown cleanup commands, and newly pulled images can be removed by exact tag once no other experiment uses them.
