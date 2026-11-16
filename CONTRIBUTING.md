# Corrections and reruns

Please report adapter bugs, misleading comparisons, changed downloads, or missing settings. Include the command, engine/client versions, actual query plan where relevant, and the smallest example that demonstrates the issue.

For a hardware rerun, use a clean clone and keep the original results unchanged. Share the new preparation record, all raw query latencies/IDs, exact references, hardware/OS, container resource limits and image digests, requirement locks, and any failures. Say whether you changed corpus size, embeddings, filter selectivity, warmups, index parameters, cache policy or concurrency. A 1,000-passage smoke run belongs in its own directory and must not replace the full table.

Check results with `py -3.12 scripts/verify_results.py --run runs/proof --n 1000`. Remove host paths, account names, secrets, personal contact details and downloaded books/models before sharing. Use a neutral commit identity. Keep public contributions small: result JSON, CSV, commands and documentation are sufficient. No hosted CI is required.

Run the real retrieval and persistence checks for an adapter change. Explain what behavior changed and include both the old and new results when correcting a published measurement.
