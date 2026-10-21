# Candidate model benchmark (CPU only)

Run 2026-10-21 13:48 on Intel64 Family 6 Model 183 Stepping 1, GenuineIntel, 16 physical cores, 24 GB RAM. llama.cpp `llama-server` CPU build, **4 threads**, context 4096, greedy decoding, thinking disabled for hybrid-reasoning models.

HumanEval: 40-problem subset (seed 0), pass@1. Debug: 12 buggy beginner functions, fixed = unit tests pass. Quiz: 30 multiple-choice programming/CS/AI questions.

| Model | Params | Quant file | Size | Peak RAM | Startup | Gen tok/s | Prompt tok/s | HumanEval | Debug | Quiz | Tutor reply |
|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen2.5-coder-0.5b | 0.5B | `qwen2.5-coder-0.5b-instruct-q4_k_m.gguf` | 0.49 GB | 835 MB | 1.0 s | 70.4 | 417.2 | 55% | 25% | 50% | 1.96 s |
| qwen3.5-0.8b | 0.8B | `Qwen3.5-0.8B-Q4_0.gguf` | 0.56 GB | 5430 MB | 1.32 s | 45.5 | 415.3 | 25% | 25% | 83% | 7.62 s |
| qwen2.5-coder-1.5b | 1.5B | `qwen2.5-coder-1.5b-instruct-q4_k_m.gguf` | 1.12 GB | 2341 MB | 1.8 s | 27.7 | 227.1 | 62% | 67% | 80% | 9.68 s |
| qwen3-1.7b | 1.7B | `Qwen3-1.7B-Q4_K_M.gguf` | 1.28 GB | 4588 MB | 1.76 s | 25.0 | 208.8 | 57% | 75% | 63% | 9.24 s |
| qwen3.5-2b | 2B | `Qwen3.5-2B-Q4_K_M.gguf` | 1.28 GB | 6355 MB | 1.85 s | 20.3 | 189.2 | 62% | 92% | 83% | 14.45 s |
| granite-4.2-3b | 3B | `granite-4.2-3b-Q4_K_M.gguf` | 2.24 GB | 5681 MB | 2.48 s | 13.2 | 94.1 | 85% | 100% | 87% | 22.05 s |

> **Note:** the Peak RAM column above was measured with llama-server defaults (8 GB in-RAM prompt cache, weight repacking) and is **inflated**. Use `memory_probe.json` (lean settings: `--cache-ram 0 --ctx-checkpoints 1 --no-repack`) for real memory needs. See `docs/milestone-1-report.md`, section 5.3.
