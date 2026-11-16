# Clean-clone proof run: 1,000 passages

This run started with a fresh local Git clone, no environment and no generated data. The PowerShell command downloaded all 14 original books and the pinned ONNX model, generated real CPU embeddings for 1,000 passages and 300 queries, then ran all nine engines / 13 configurations sequentially. `verification.json` recomputes every saved median/p95 and recall, verifies book filters, and checks the persisted state. Every server was restarted before its separate reopen command.

`input-equality.json` shows that these newly generated document vectors are bitwise equal to the corresponding first 1,000 vectors in the full workload, and all 300 query vectors also match. No full-run data or model cache was copied into this clone.

Run command: `powershell -NoProfile -ExecutionPolicy Bypass -File .\reproduce.ps1 -Size 1000 -Output runs/proof`. Exact source commit and file hashes are in `source.json`; `commands.json` preserves actual command arguments and return codes with host locations replaced by portable paths. `stdout/` contains successful preparation, adapter and reopen output. Requirement snapshots are in `versions/`, image IDs/digests in `container-versions.json`, cleanup return codes in `docker-cleanup.json`.

These are functionality measurements on a small corpus. Qdrant may use exact scans below its indexing threshold; PostgreSQL can choose sequential scans despite an HNSW index. Do not replace the 20,000-passage table with these timings. The original and reduced runs remain separate.

| Configuration | Plain p50 / p95 ms | Book filter p50 / p95 ms | Recall@5 plain / filter |
|---|---:|---:|---:|
| Chroma | 0.64 / 0.86 | 0.99 / 1.29 | 100.00% / 100.00% |
| Qdrant local | 0.77 / 0.91 | 4.83 / 5.59 | 100.00% / 100.00% |
| LanceDB | 2.59 / 3.03 | 3.14 / 3.65 | 100.00% / 100.00% |
| FAISS | 0.07 / 0.10 | 0.09 / 0.13 | 100.00% / 100.00% |
| Qdrant named volume | 13.14 / 26.34 | 12.86 / 26.13 | 100.00% / 100.00% |
| Qdrant Windows bind | 12.91 / 26.27 | 2.32 / 25.73 | 100.00% / 100.00% |
| pgvector/exact | 1.59 / 1.86 | 0.69 / 0.80 | 100.00% / 100.00% |
| pgvector/hnsw | 1.59 / 1.77 | 0.68 / 0.81 | 100.00% / 100.00% |
| pgvector/hnsw-exact-filter | 1.59 / 1.79 | 0.70 / 0.85 | 100.00% / 100.00% |
| milvus/configured | 2.39 / 2.65 | 2.31 / 2.62 | 100.00% / 100.00% |
| weaviate/configured | 1.17 / 1.29 | 1.19 / 1.31 | 100.00% / 100.00% |
| sqlite-vec/configured | 0.84 / 0.94 | 0.69 / 0.77 | 100.00% / 100.00% |
| hnswlib/configured | 0.04 / 0.08 | 0.25 / 0.29 | 100.00% / 100.00% |

Only small evidence files are included. Downloaded books, models, generated arrays, databases and virtual environments were removed after this run.

The cleanup helper was subsequently improved for Windows long paths and tested on the actual remaining bind-mount files. Its tested digest and output are in `cleanup-validation.json`; `source.json` records this separately from the unchanged benchmark pipeline.
