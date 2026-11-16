# Third-party terms

The MIT license in this repository covers the benchmark code and documentation. Dependencies, downloaded model files and books retain their own terms; they are not relicensed by this project. Checked against upstream sources on 2026-11-16.

| Component used | Upstream terms / source |
|---|---|
| Chroma 1.5.9 | [Apache-2.0](https://github.com/chroma-core/chroma/blob/1.5.9/LICENSE) |
| Qdrant server 1.20.1 | [Apache-2.0](https://github.com/qdrant/qdrant/blob/v1.20.1/LICENSE) |
| qdrant-client 1.20.0 | [Apache-2.0](https://github.com/qdrant/qdrant-client/blob/v1.20.0/LICENSE) |
| LanceDB 0.41.0 | [Apache-2.0](https://github.com/lancedb/lancedb/blob/v0.41.0/LICENSE) |
| FAISS 1.16.0 | [MIT](https://github.com/facebookresearch/faiss/blob/v1.16.0/LICENSE) |
| pgvector 0.8.7 | [PostgreSQL License](https://github.com/pgvector/pgvector/blob/v0.8.7/LICENSE) |
| PostgreSQL | [PostgreSQL License](https://www.postgresql.org/about/licence/) |
| Milvus 3.0.6 | [Apache-2.0](https://github.com/milvus-io/milvus/blob/v3.0.6/LICENSE) |
| Weaviate 1.40.5 | [Per-directory terms](https://github.com/weaviate/weaviate/blob/v1.40.5/LICENSE): code outside `wl/` uses BSD-3-Clause; `wl/` requires separate enterprise terms. This benchmark uses self-provided vectors and no enterprise license key. |
| sqlite-vec 0.1.9 | [MIT](https://github.com/asg017/sqlite-vec/blob/v0.1.9/LICENSE-MIT) or [Apache-2.0](https://github.com/asg017/sqlite-vec/blob/v0.1.9/LICENSE-APACHE) |
| hnswlib 0.8.0 | [Apache-2.0](https://github.com/nmslib/hnswlib/blob/v0.8.0/LICENSE) |
| FastEmbed | [Apache-2.0](https://github.com/qdrant/fastembed/blob/main/LICENSE) |
| BAAI/bge-small-en-v1.5 model | [MIT model card](https://huggingface.co/BAAI/bge-small-en-v1.5); the [pinned ONNX conversion](https://huggingface.co/Qdrant/bge-small-en-v1.5-onnx-Q/blob/aa8f8b060edb00e03bfdd08813a2949946c8ba55/README.md) is recorded in `corpus/model.json`. |

The driver also downloads official container images and their dependencies. Their notices remain in those images. Python clients and transitive dependencies carry their own licenses; the requirement locks identify the exact packages used, rather than changing those terms.

All 14 books are recorded by Project Gutenberg as public domain in the USA. Each title, original text URL, rights-page URL and measured text checksum is in [corpus/sources.json](corpus/sources.json). The downloader retains the original files and rights pages locally, then removes Gutenberg boilerplate only for chunking. No book files are distributed here. The [Project Gutenberg license and trademark conditions](https://www.gutenberg.org/policy/license.html) and the copyright rules in your location still apply to your own use and redistribution.
