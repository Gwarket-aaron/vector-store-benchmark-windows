# Windows 向量儲存實測

[English](README.md)

加上「只查這本書」的條件之後，向量搜尋會慢多少、又會漏掉多少近鄰？這份專案用同一批真實文本與 CPU embedding，測試 **9 個引擎、13 種部署或查詢設定**：Chroma、Qdrant、LanceDB、FAISS、pgvector、Milvus、Weaviate、sqlite-vec 與 hnswlib。你可以查看每次查詢的延遲與回傳 ID，也可以在自己的 Windows 電腦重跑。

## 測試怎麼做

14 本 Project Gutenberg 美國公有領域英文書，輪流取出 20,000 段，每段 96 個空白分隔單字、步長 80。FastEmbed 0.9.1 以兩條 CPU 執行緒執行 BGE-small-en-v1.5 ONNX，產生 384 維、正規化 float32 向量。原始文件 embedding 耗時 634.12 秒，沒有算進資料庫計時。

查詢由 100 個文學主題搭配三種問法組成，共 300 題；不是人工相關性標註。每套先做 20 次無篩選暖機，再各做 300 次全表與指定 `book_id` 搜尋，k=5。回傳 ID、原文及 metadata，不取回向量；每筆原文與書籍 ID 都核對來源。書籍篩選涵蓋全表的 1.655%–8.44%。

同一台 Windows 11 build 26300，Python 3.12.10、Ryzen 7 9800X3D（8 核心／16 執行緒）、RAM 33,408,679,936 bytes、Predator GM7 SSD；Docker Desktop 4.86.0／Linux Engine 29.7.2。伺服器容器分配 2 CPU／2 GiB，Milvus 為 4 GiB。hnswlib 在 Linux Python 容器內執行，沒有 RPC。

## 2026-11-16 結果

請把延遲和 recall 一起看。**recall@5 是與相同候選集合的精確向量 top 5 重疊比例**，不是文章是否有用，也不是 AI 回答正確率。下表為顯示而四捨五入，[CSV](results/summary.csv) 與 [JSON](results/combined.json) 保留完整精度。

| 引擎／部署 | 版本 | 執行方式／索引 | 寫入秒 | 建索引／等待 | 無篩選 p50／p95 ms | 書籍篩選 p50／p95 ms | recall@5 無篩選／篩選 |
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

pgvector 三列共用同一次寫入與索引建置，不要把時間相加。第一列先測尚未建 HNSW 的 exact 查詢；第三列把書籍篩選改成 MATERIALIZED 子集合後精確排序，全表仍走預設 planner。縮成 5,000 段時，planner 即使有索引也改選精確掃描，所以小資料不一定會重現 20k 的 recall 損失。

Qdrant 另列的時間是寫入確認後等待 optimizer 穩定；Milvus 的 flush／index／load 另計；Weaviate 的同步建索引包含在寫入。FAISS 寫入時間含保存 index 與原文 JSON，篩選計時含 Python metadata 掃描與 ID selector。hnswlib 書籍篩選使用 Python callback 與一條執行緒，全表查詢使用兩條。表中的部署與應用程式路徑不同。

Qdrant Windows bind mount 實際出現檔案系統安全警告，因此另保留 Linux named volume 的完整重跑。那次延遲沒有改善；自己的伺服器實驗建議採 named volume 設定。

## 在自己的電腦重跑

準備 64 位元 Python 3.12.10、Git、PATH 上的 uv，以及已啟動 Linux containers 的 Docker Desktop。在全新的 clone 內開 Windows PowerShell：

```powershell
py -3.12 --version
uv --version
docker version
powershell -NoProfile -ExecutionPolicy Bypass -File .eproduce.ps1 -Size 1000 -Output runs/proof
```

完成後 `runs/proof/completed.json` 與 `verification.json` 應顯示 PASS：1,000 段、300 題、13 種設定。程式分開建立三個虛擬環境，保留各輪 grpc／protobuf 固定版本；真正下載原文與模型、重算 CPU embedding，再依序執行。每套都測更新、刪除及新程序重開；伺服器另做 restart 後重查。結束時移除自己建立的 Docker container、volume 與新下載 image。

完整資料量改用新 clone，把 `-Size 1000` 改成 `-Size 20000`。只跑五個 Windows 內嵌引擎可加 `-NativeOnly`。各工具指令、Docker 參數與清理方式見 [REPRODUCING.md](REPRODUCING.md)。每次使用新的輸出資料夾；上游文本雜湊不同會停止，避免混用不同版本。

## 適用範圍

這是同一台機器、同一份英文文學資料、依序執行的結果，沒有清除 OS cache，也沒有排除其他背景工作。HTTP、gRPC 與程序內呼叫的成本不同；各 HNSW 設定沒有調成同一 recall。不能據此選出普遍速度冠軍、比較引擎記憶體成本或推論大規模服務表現。

同機不同輪 Chroma 無篩選 p95 為 1.48／2.31 ms，FAISS 為 1.15／0.22／0.31 ms；縮小資料也可能反轉延遲排序。更新、刪除與正常重啟通過，沒有測斷電耐久性、跨 sidecar 交易、並行吞吐、HA 或 LLM 回答品質。

[完整原始結果](results/full/)、[數值來源](results/provenance.json)、[書籍來源](corpus/sources.json)、[模型版本](corpus/model.json) 與 [縮小重跑](results/proof/) 各自保留。專案不附書籍全文、模型、向量或資料庫。公開 JSON 只在兩個文字欄位移除本機路徑與內部來源標籤，所有數值原樣保留。

程式採 [MIT](LICENSE)；工具、模型與書籍各有自己的[授權條件](THIRD-PARTY-NOTICES.md)。歡迎[修正與不同硬體重跑](CONTRIBUTING.md)。更多工具可看 [Gwarket 工具庫](https://gwarket.com/tools/) 或 [English library](https://gwarket.com/en/tools/)。
