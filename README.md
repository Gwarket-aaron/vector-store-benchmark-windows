# Vector store benchmark on Windows

[繁體中文](README.zh-TW.md)

How much does a book filter change vector-search latency and recall? This repository runs the same literature retrieval task through **nine engines**: Chroma, Qdrant, LanceDB, FAISS, pgvector, Milvus, Weaviate, sqlite-vec, and hnswlib. It includes 13 deployment/query configurations, every query's latency and returned IDs, and a small reproduction you can run on a Windows workstation without an API key.

Use this to inspect the cost of a particular retrieval path and reproduce it on your hardware. The table is one workload observation; it is not a universal speed ranking.

## Workload and machine

- **20,000 passages from 14 public-domain English books**, downloaded from Project Gutenberg. Each passage has 96 whitespace-delimited words, stride 80; books are sampled round robin.
- **Real CPU embeddings:** FastEmbed 0.9.1, BGE-small-en-v1.5 ONNX, two threads, 384-dimensional normalized float32 vectors. The model revision and file checksums are pinned. Passage embedding took 634.12 s in the original preparation, outside database timings.
- **300 programmatically composed queries:** 100 literature topics in three question forms. Each store receives the same vectors, queries and `book_id` constraints. These are not human relevance labels or a held-out question-answering test.
- **k=5**, 20 unfiltered warmups, then 300 unfiltered and 300 book-filtered requests. Every response contains IDs, original text and metadata; vectors are omitted. Returned text and book IDs are checked against the source.
- **Host:** Windows 11 build 26300, Python 3.12.10, AMD Ryzen 7 9800X3D (8 cores / 16 threads), 33,408,679,936 bytes RAM, Predator GM7 SSD. Docker Desktop 4.86.0 / Linux Engine 29.7.2. Server containers have two CPUs and 2 GiB RAM, except Milvus at 4 GiB. hnswlib runs inside a two-CPU / 2 GiB Linux Python container with no RPC.

## Measured results — 2026-11-16

Read latency together with recall. **Recall@5 measures overlap with the exact top five vectors in the eligible corpus**, not passage usefulness or answer quality. Book filters match 1.655%–8.44% of the full corpus. Display values are rounded; [CSV](results/summary.csv) and [JSON](results/combined.json) retain the original precision.

| Store / deployment | Version | Execution / index | Ingest s | Index / wait | Plain p50 / p95 ms | Book filter p50 / p95 ms | Recall@5 plain / filter |
|---|---|---|---:|---|---:|---:|---:|
| Chroma native | 1.5.9 | embedded; HNSW cosine | 17.54 | included / no separate index | 1.18 / 1.48 | 13.83 / 17.83 | 95.00% / 100.00% |
| Qdrant local native | 1.20.0 | embedded; exact cosine | 77.64 | included / no separate index | 25.48 / 33.60 | 120.77 / 158.85 | 100.00% / 100.00% |
| LanceDB native | 0.41.0 | embedded; exact cosine, no index | 0.79 | included / no separate index | 6.27 / 8.02 | 6.33 / 9.11 | 100.00% / 100.00% |
| FAISS native | 1.16.0 | library; exact FlatIP + IDMap2 | 0.14 | included | 0.34 / 1.15 | 2.05 / 3.04 | 100.00% / 100.00% |
| Qdrant server Windows bind mount | 1.20.1 | HTTP server / Windows bind; HNSW cosine | 8.55 | 14.83s optimizer wait after acknowledged ingestion | 3.52 / 27.40 | 9.53 / 28.77 | 98.27% / 99.93% |
| Qdrant server Linux named volume | 1.20.1 | HTTP server / Linux volume; HNSW cosine | 3.55 | 5.14s optimizer wait after acknowledged ingestion | 15.41 / 29.70 | 15.35 / 29.40 | 97.40% / 99.87% |
| pgvector exact | 0.8.7 / PostgreSQL17 | SQL server; exact cosine | 2.24 | none (before HNSW creation) | 26.89 / 32.00 | 3.73 / 5.01 | 100.00% / 100.00% |
| pgvector hnsw | 0.8.7 / PostgreSQL17 | SQL server; HNSW, default planner | 2.24 | 2.43s create/flush/index/load | 1.22 / 1.36 | 1.42 / 3.60 | 96.60% / 87.53% |
| pgvector HNSW + exact book subset | 0.8.7 / PostgreSQL17 | SQL server; HNSW + exact book subset | 2.24 | 2.43s create/flush/index/load | 1.19 / 1.33 | 3.71 / 4.20 | 96.60% / 100.00% |
| milvus | 3.0.6 / PyMilvus3.0.3 | gRPC server; HNSW cosine | 1.54 | 5.99s create/flush/index/load | 2.31 / 2.67 | 2.75 / 3.27 | 94.93% / 99.07% |
| weaviate | 1.40.5 / client4.24.1 | gRPC server; HNSW cosine / ACORN | 4.64 | included in insertion | 1.30 / 1.40 | 1.84 / 1.99 | 94.67% / 96.87% |
| sqlite-vec | 0.1.9 | embedded; exact vec0 cosine | 0.58 | none (exact scan) | 19.64 / 29.59 | 18.76 / 24.19 | 100.00% / 100.00% |
| hnswlib | 0.8.0 | Linux container, no RPC; HNSW cosine | 1.25 | included in insertion | 0.10 / 0.14 | 2.61 / 7.93 | 94.73% / 99.87% |

The pgvector rows share one ingestion and index build; do not add those times. Its exact phase runs before HNSW creation. In the final phase, plain search remains on the default planner path while the book-filtered query materializes the eligible subset and sorts it exactly. EXPLAIN plans are in the raw results. At 5,000 passages the planner chose exact scans even after index creation, so a small rerun need not reproduce the full-run recall loss.

Qdrant's separate wait is optimizer settling after acknowledged ingestion. Milvus separately times flush/index/load. Weaviate builds its synchronous index during ingestion. FAISS ingestion includes saving the index and JSON sidecar; filtered requests include the Python metadata scan and ID selector. hnswlib uses a Python callback and one query thread for filtered requests, two for plain requests. These are different application paths, not equivalent engine-only microbenchmarks.

The Qdrant Windows bind-mount run emitted a filesystem safety warning. Its Linux named-volume rerun is retained separately; changing the mount did not improve that run's latency. Prefer the named-volume configuration for your own server experiment.

## Reproduce

You need **64-bit Python 3.12.10**, Git, `uv` on PATH and Docker Desktop with Linux containers running. Downloads need internet access; embedding uses only the CPU. Run inside a fresh clone from Windows PowerShell:

```powershell
py -3.12 --version
uv --version
docker version
powershell -NoProfile -ExecutionPolicy Bypass -File .eproduce.ps1 -Size 1000 -Output runs/proof
```

Expect `runs/proof/completed.json` and `runs/proof/verification.json` to say `PASS`, with 1,000 passages, 300 queries and 13 configurations. The driver creates three separate virtual environments to preserve incompatible grpc/protobuf pins, downloads the corpus and pinned model, computes fresh embeddings, runs stores sequentially, checks updates/deletes and new-process reopening, and restarts every server before checking persistence. It removes its own Docker containers, volumes and newly pulled images in `finally`. See [REPRODUCING.md](REPRODUCING.md) for commands by store, Docker settings, output files and cleanup.

For the full workload, use a new clone and change `-Size 1000` to `-Size 20000`. For embedded stores only, add `-NativeOnly` (Chroma, Qdrant local, LanceDB, FAISS, sqlite-vec; five engines). Never reuse an output directory. Corpus checksums must match the original source record; a changed upstream text causes a clear failure rather than silently mixing inputs.

## What these numbers leave open

One machine, one English literature workload, sequential runs, no cold-cache control, no isolation from other host processes, and no concurrency/load scaling. Runs occurred at different times on the same day. HTTP, gRPC and in-process calls have different overheads. Approximate indexes use the stated settings rather than being tuned to equal recall. Memory limits differ, and the recorded RSS/disk fields do not support an engine memory-cost ranking.

Earlier and later Chroma runs had unfiltered p95 of 1.48 and 2.31 ms; FAISS reruns had p95 of 1.15, 0.22 and 0.31 ms. Small-data runs can reverse latency order. Updates, deletion and normal restart succeeded; power-loss durability, transactions across sidecar files, HA, security and LLM answer quality were not evaluated.

## Data, code and corrections

[Raw full-run results](results/full/), [numeric provenance](results/provenance.json), [corpus sources](corpus/sources.json), [model revision](corpus/model.json), and [proof run](results/proof/) are kept separately. Books, weights, generated vectors and databases are downloaded/generated locally and are not bundled. Only host-path text and an internal source label were removed from two full-run JSON strings; all numeric fields are unchanged.

Code is [MIT licensed](LICENSE). Stores, model weights and corpus have their own [third-party terms](THIRD-PARTY-NOTICES.md). [Corrections and reruns](CONTRIBUTING.md) are welcome.

More from Gwarket: [AI tools library](https://gwarket.com/en/tools/) · [繁體中文工具庫](https://gwarket.com/tools/). Individual store tutorials are not linked here until available publicly.
