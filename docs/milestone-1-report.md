# Edu.ai — Milestone 1 Report

**Requirements, hardware budget, model comparison and architecture**
Date: 2026-10-21 · Status: Milestone 1 complete · No application code written yet (by design: the spec asks for model selection and architecture before the prototype)

---

## 1. Summary

| Question | Answer |
|---|---|
| **Recommended default model** | **Qwen3.5-2B** (Apache-2.0), Q4_K_M GGUF, 1.28 GB file, **1.45 GB peak RAM**, ~21 tokens/s on 4 CPU threads |
| **Recommended "quality mode"** | **Granite-4.2-3B** (Apache-2.0), 2.24 GB file, 2.4 GB peak RAM, ~14 tokens/s. Best on every quality test. |
| **4 GB PCs** | Feasible only as a *lite* mode with **Qwen3.5-0.8B** (0.76 GB RAM): good concept answers (83% quiz) but weak code (25% HumanEval subset). Code features must be checked by running tests, not trusted. Qwen3.5-2B *might* fit at 4 GB with a short context; it must be tested on a real 4 GB machine. |
| **Runtime** | llama.cpp `llama-server`, CPU build (**23 MB** download), started with `--cache-ram 0 --ctx-checkpoints 1 --no-repack` |
| **Fine-tuning?** | Not yet. The spec says fine-tune only if it beats the baseline; first build prompts + retrieval + execution checks, then measure. |
| **Biggest finding** | Sub-1B models often **return the buggy code unchanged while claiming they fixed it** (Qwen2.5-Coder-0.5B did this on 6 of 12 tasks). For a tutor, this is worse than a wrong answer. Edu.ai must verify code fixes by execution before presenting them as fixed. |

---

## 2. What was done

1. **Surveyed current small models** (October 2026) via the Hugging Face API and web search. Published third-party benchmark numbers disagreed with each other, so every candidate was measured locally instead of trusting them.
2. **Chose six candidates** from 0.5B to 3B parameters, all Apache-2.0, all with official or widely used GGUF builds (section 4).
3. **Set up the project** at `Edu.ai/`: a Python virtual environment, the llama.cpp CPU runtime (build b11780), and the six quantized models (6.8 GB total, git-ignored).
4. **Built three task sets**:
   - a fixed **40-problem subset of HumanEval** (seed 0), scored pass@1 by running each answer against the official tests;
   - **12 buggy beginner functions** with unit tests, written for this project. Each was validated: every buggy version fails its tests and a reference fix passes;
   - a **30-question multiple-choice quiz** on programming, algorithms and AI/ML, with the answer letters spread A/B/C/D to avoid position bias.
5. **Built a benchmark harness** (`benchmarks/bench_models.py`). It starts `llama-server` for each model with **4 CPU threads** and a 4,096-token context, runs all three task sets with greedy decoding, times a typical tutoring reply, and records startup time, RAM and speed. Generated code runs in a separate, time-limited process (`benchmarks/sandbox.py`).
6. **Ran the full benchmark** (about 50 minutes for all six models).
7. **Investigated suspicious RAM readings** and re-measured with corrected server settings (`benchmarks/memory_probe.py`), then measured the speed cost of those settings (`benchmarks/repack_speed.py`).
8. **Analysed failures** (`benchmarks/analyze_failures.py`): classified every failed debugging answer as *unchanged code*, *no code*, or *wrong fix*.

---

## 3. Hardware budget (assumptions to validate)

| Target PC | RAM left for Edu.ai (estimate) | Implication |
|---|---|---|
| **4 GB, Windows 10/11** | ~1.2–1.5 GB (Windows plus a browser commonly use 2.5–3 GB at idle) | Model + runtime must stay **under ~1 GB**, or ~1.5 GB with nothing else open |
| **8 GB** | ~4–5 GB | 2B models comfortable; 3B fine |
| **4 GB, lightweight Linux** | ~2.5–3 GB | 2B likely workable |

These are estimates, not measurements. The benchmark ran on a high-end laptop (Intel i7-14650HX, 24 GB RAM) with inference **limited to 4 threads** to approximate a modest CPU. A genuinely low-end CPU (older dual-core, single-channel memory, no AVX2) will be **slower**: expect 2–4× lower tokens/s. Milestone 6 must re-measure on a real low-end machine or a VM capped at 4 GB.

---

## 4. Candidates

| Model | Params | Released | License | Why included |
|---|---|---|---|---|
| Qwen2.5-Coder-0.5B-Instruct | 0.5B | 2024 | Apache-2.0 | Smallest code-specialised model |
| Qwen3.5-0.8B | 0.8B | Feb 2026 | Apache-2.0 | Newest tiny general model |
| Qwen2.5-Coder-1.5B-Instruct | 1.5B | 2024 | Apache-2.0 | Popular small coding model |
| Qwen3-1.7B | 1.7B | 2025 | Apache-2.0 | Strong small general model |
| Qwen3.5-2B | 2B | Feb 2026 | Apache-2.0 | Newest small Qwen |
| Granite-4.2-3B | 3B | Aug 2026 | Apache-2.0 | Newest 3B, IBM, upper bound for 8 GB PCs |

**Considered and excluded (not benchmarked):**
- **Qwen2.5-Coder-3B**: Qwen Research licence, not open for commercial use.
- **Gemma 4 E2B** (Apache-2.0): its official Q4_0 GGUF is **3.35 GB**, too large for the 4 GB target. Worth revisiting for 8 GB PCs.
- **Phi-4-mini** (3.8B, MIT): above the 3B range in the spec.
- **Llama 3.2 1B/3B**: older, with a more restrictive community licence. Newer Apache-2.0 models cover the same size range.

---

## 5. Results

All runs: llama.cpp b11780 CPU build, 4 threads, 4,096 context, greedy decoding. "Thinking" was disabled for the hybrid-reasoning models (Qwen3, Qwen3.5, Granite 4.2) to keep tutoring replies fast. Raw outputs are in `benchmarks/results/*.raw.json`.

### 5.1 Quality

| Model | HumanEval subset (pass@1, n=40) | Debug fixes (n=12) | Concept quiz (n=30) | Returned bug unchanged |
|---|---|---|---|---|
| Qwen2.5-Coder-0.5B | 55% | 25% | 50% | **7** (6 while claiming a fix) |
| Qwen3.5-0.8B | 25% | 25% | 83% | **9** |
| Qwen2.5-Coder-1.5B | 62% | 67% | 80% | 2 (both claiming a fix) |
| Qwen3-1.7B | 57% | 75% | 63% | 2 (both claiming a fix) |
| **Qwen3.5-2B** | 62% | **92%** | 83% | **0** |
| **Granite-4.2-3B** | **85%** | **100%** | **87%** | **0** |

**These samples are small.** The 95% confidence interval for a 62% score on 40 problems is about 47–75%; for 75% on 12 tasks, about 47–91%. Differences of a few points (62% vs 57%) are **not** meaningful. The big gaps are: Granite vs the rest on coding, the 2B+ models vs the sub-1B models on debugging, and Qwen2.5-Coder-0.5B on the quiz. Milestone 8 will use the full HumanEval and larger custom sets.

### 5.2 Speed and memory (with the recommended lean server settings)

| Model | File | Peak RAM | Startup | Generation | Prompt reading | Typical tutor reply* |
|---|---|---|---|---|---|---|
| Qwen2.5-Coder-0.5B | 0.49 GB | **0.51 GB** | 1.0 s | 70 tok/s | ~395 tok/s | 2.0 s |
| Qwen3.5-0.8B | 0.56 GB | **0.76 GB** | 1.3 s | 43 tok/s | ~250 tok/s | 7.6 s |
| Qwen2.5-Coder-1.5B | 1.12 GB | **1.15 GB** | 1.8 s | 28 tok/s | ~215 tok/s | 9.7 s |
| Qwen3-1.7B | 1.28 GB | **1.60 GB** | 1.8 s | 26 tok/s | ~225 tok/s | 9.2 s |
| **Qwen3.5-2B** | 1.28 GB | **1.45 GB** | 1.9 s | 21 tok/s | ~195 tok/s | 14.5 s |
| Granite-4.2-3B | 2.24 GB | **2.41 GB** | 2.5 s | 14 tok/s | ~103 tok/s | 22.1 s |

\*"What is a Python list? Explain simply with a short example", up to 300 tokens, timed end to end. With streaming, students see text after about a second; the full reply takes this long.

### 5.3 Effect of the server memory settings

Peak RAM after 12 varied prompts (`benchmarks/results/memory_probe.json`):

| Model | llama-server defaults | Prompt cache off | + repacking off |
|---|---|---|---|
| Qwen2.5-Coder-0.5B | 572 MB | 539 MB | **510 MB** |
| Qwen3.5-0.8B | 1,481 MB | 1,026 MB | **758 MB** |
| Qwen2.5-Coder-1.5B | 1,818 MB | 1,743 MB | **1,147 MB** |
| Qwen3-1.7B | 2,525 MB | 2,241 MB | **1,595 MB** |
| Qwen3.5-2B | 2,393 MB | 1,939 MB | **1,448 MB** |
| Granite-4.2-3B | 4,072 MB | 3,855 MB | **2,406 MB** |

Turning repacking off did **not** slow generation on this CPU; it was equal or slightly faster for every model. Prompt reading was also unchanged, except for the one Q4_0 file (Qwen3.5-0.8B: 401 → 248 tok/s). So Edu.ai will run Q4_K_M models with `--no-repack`, and keep repacking for Q4_0 files.

---

## 6. Failure analysis

- **"Fixed" without fixing.** Qwen2.5-Coder-0.5B returned the original buggy code 7 times, 6 of them introduced with phrases like *"Here's the corrected function"* plus an invented explanation. Qwen2.5-Coder-1.5B and Qwen3-1.7B did the same twice each. A beginner cannot spot this.
- **Diagnoses but doesn't fix.** Qwen3.5-0.8B usually explained the bug, sometimes correctly (case-sensitive vowel check) and sometimes half-wrong (it claimed the loop also skipped the *last* element). It then returned the original code 9 times.
- **Knowledge vs code.** Qwen3.5-0.8B scored 83% on concepts but 25% on HumanEval. Qwen2.5-Coder-0.5B is the reverse: 55% coding, 50% concepts. Neither is balanced enough to be the main tutor.
- **No formatting failures from the larger models.** Every model wrapped HumanEval answers in code blocks, so the scores reflect code quality, not parsing.

**Design consequence:** before Edu.ai says "fixed", it should (1) check that the code actually changed, and (2) when tests exist, run them in the sandbox. This guardrail matters most for the 4 GB lite mode.

---

## 7. Recommendation and trade-offs

| | Lite (4 GB) | **Default (8 GB)** | Quality (8 GB+, patient) |
|---|---|---|---|
| Model | Qwen3.5-0.8B | **Qwen3.5-2B** | Granite-4.2-3B |
| Peak RAM | 0.76 GB | 1.45 GB | 2.41 GB |
| Speed | 43 tok/s | 21 tok/s | 14 tok/s |
| Strength | Concepts, speed | Balanced; best debugging among ≤2B; no false fixes | Best on all tests |
| Weakness | Code generation and fixing | 62% coding subset | Slowest; 2.2 GB download |

**Why Qwen3.5-2B as the default:** it uses *less* RAM than Qwen3-1.7B and only 0.3 GB more than Qwen2.5-Coder-1.5B. It had the best debugging score of any model at or below 2B, never returned unchanged code, and matched the best quiz score in its size class. Its HumanEval score equals Qwen2.5-Coder-1.5B within noise. Granite is clearly better on coding, but it is about 35% slower and 65% heavier.

**Trade-offs to keep in mind:**
- **Size vs quality:** going from 2B to 3B bought +23 points on the coding subset, at +1 GB RAM and −35% speed.
- **Speed on real low-end CPUs:** expect roughly half to a quarter of the speeds above. Qwen3.5-2B could drop to 5–10 tok/s, which is still usable with streaming. Granite could drop to 3–7 tok/s, which is slow.
- **Thinking mode:** disabled here. Enabling it may improve accuracy on harder problems but multiplies response time. It will be tested as an optional "think harder" button.
- **Training cost:** none so far. LoRA fine-tuning of a 2B model in 4-bit fits on an 8 GB consumer GPU (such as the RTX 5060 used for previous projects), but it is only worth doing if it beats prompts + retrieval in Milestone 8.

---

## 8. Proposed architecture

```
┌──────────────────────────── Edu.ai (all local, offline) ────────────────────────────┐
│                                                                                      │
│  Browser UI (static HTML/JS, no build step; vendored marked + highlight.js)          │
│    chat · code highlighting · level & mode picker · settings · progress              │
│                │  HTTP + streaming (SSE), localhost only                             │
│                ▼                                                                     │
│  Python backend (FastAPI)                                                            │
│    ├─ Tutor engine: mode detection (explain / hint / debug / code / quiz / project), │
│    │  student level, teaching sequence, homework policy (hints before solutions)     │
│    ├─ Prompt templates (versioned files)                                             │
│    ├─ Retrieval: SQLite FTS5 (BM25) over curated notes, no embedding model needed   │
│    ├─ Verifier: "did the code change?" + run tests in sandbox before saying "fixed"  │
│    ├─ Sandbox: separate process, timeout, temp dir, memory cap (Windows Job object / │
│    │  Linux rlimits), no network where the OS allows                                 │
│    └─ Storage: SQLite (chats, progress), stays on the device                         │
│                │  OpenAI-compatible HTTP, localhost                                  │
│                ▼                                                                     │
│  llama-server (llama.cpp CPU build, 23 MB) + one GGUF model                          │
│    --cache-ram 0 --ctx-checkpoints 1 --no-repack, configurable context & max tokens  │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

Key choices:
- **Inference runs in a separate process** (`llama-server`). Models can be swapped without code changes, the UI stays responsive, and a crash in one doesn't take down the other.
- **No embedding model for retrieval at first.** SQLite's built-in FTS5 gives BM25 keyword search with zero extra RAM or dependencies. Embeddings get added only if evaluation shows BM25 misses too much.
- **Verification over trust.** Section 6 shows why.

---

## 9. Milestone plan

| # | Milestone | Main deliverables | Done when |
|---|---|---|---|
| 2 | Minimal local inference | `eduai/inference.py` (start/stop llama-server, health, streaming chat), model registry, CLI chat | Streams answers offline from the chosen model; tests pass with a fake server |
| 3 | Chat interface | FastAPI backend, static web UI, chat history in SQLite, settings (model, context, max tokens) | Usable in a browser on localhost; history persists |
| 4 | Tutoring prompts + retrieval | Mode/level templates, homework policy, curated notes (Python basics, DSA, AI/ML), FTS5 retrieval | Retrieval measurably improves quiz/explanation scores vs prompt-only |
| 5 | Dataset + optional LoRA | Data pipeline (dedup, quality filter, leak-free split), LoRA training script | Fine-tune kept **only** if it beats Milestone 4 on held-out tests |
| 6 | Quantization + low-end profiling | Q4_K_M vs Q5/Q8 regression check, 4 GB VM measurements, startup/RAM report | Real numbers on a 4 GB machine; lite/default thresholds confirmed |
| 7 | Sandbox + verifier | Job-object/rlimit sandbox, "code changed?" + test-run verifier, static checks | Malicious-code tests are contained; false "fixed" claims blocked |
| 8 | Evaluation | Full HumanEval, larger debug/quiz sets, level-adaptation and hallucination checks, human review sheet | Reproducible report with confidence intervals |
| 9 | Packaging | Windows + Linux offline installers, model download script, docs | Fresh offline install works on a clean machine |

---

## 10. Mistakes, problems and corrections

| What happened | Impact | How it was handled |
|---|---|---|
| **The first RAM numbers were wrong.** The full benchmark reported peaks of 4.6–6.4 GB for 1.7–3B models. Cause: this `llama-server` version keeps an **8 GB prompt cache in RAM by default**, plus 32 context checkpoints per conversation for hybrid models. It grew across the benchmark's 83 different prompts. | Taken at face value, these numbers would have ruled out every model above 0.5B for 4 GB PCs. That conclusion was wrong. | Spotted because RAM was far above file size. Found the flags, re-measured all models with three settings (section 5.3), and verified the speed cost. The 4.6–6.4 GB figures in `summary.md` are **superseded** by `memory_probe.json`. |
| **Weight repacking doubled part of the memory.** llama.cpp keeps a repacked copy of the weights for faster CPU maths. | +30–60% RAM. | Measured that it gave no generation speedup here, so it gets disabled for Q4_K_M files. |
| **Granite-4.2-3B returned an empty answer** in the first smoke test. It's a hybrid-reasoning model, and its hidden "thinking" used the whole token budget. | It would have scored near 0% and been wrongly rejected. | Inspected the raw response, confirmed `enable_thinking: false` works, and marked it as a thinking model in the harness before the full run. |
| **The llama.cpp "latest release" was a placeholder** (`v0.7.0` containing only `nightly-tag.txt`). Real builds are published as pre-releases (`b11xxx`). | Short delay. | Listed the pre-releases and pinned build **b11780** for reproducibility. |
| **Published benchmark numbers conflicted.** Web sources gave inconsistent HumanEval scores and prompting setups. | They couldn't be relied on to choose a model. | Measured every candidate locally with one fixed harness. |
| **Small evaluation sets** (40 / 12 / 30 items). | Wide confidence intervals; small differences are noise. | Stated explicitly (section 5.1). The full HumanEval and larger sets are planned for Milestone 8. |
| **The benchmark sandbox is only partly isolated.** It uses a separate process, timeout, temp folder and stripped environment, but has no memory cap or network block. | Acceptable for fixed, benign benchmark tasks; **not** acceptable for running students' or models' arbitrary code in the app. | Documented in `sandbox.py`. A proper Job-object / rlimit sandbox is Milestone 7. |
| **Speed was measured on a fast CPU limited to 4 threads**, not a real low-end PC. | Real low-end speeds will be lower. | Stated as an assumption; real-hardware measurement is in Milestone 6. |
| **The first "claims a fix" detector undercounted.** It missed Qwen3.5-0.8B's phrasing. | Under-reported one failure type for one model. | Read the raw answers. The report counts *unchanged code* (reliable) separately from *claims a fix* (heuristic). |

---

## 11. What was accomplished

- A **measured, reproducible model comparison** of six current Apache-2.0 small models on CPU, covering coding, debugging, concepts, RAM, startup and speed. The scripts are in `benchmarks/`.
- A **clear recommendation with tiers**: Qwen3.5-2B default, Granite-4.2-3B quality mode, Qwen3.5-0.8B lite mode for 4 GB PCs.
- A **30–40% RAM reduction** found by correcting llama-server's defaults, with no speed loss. This is what makes 2B models realistic on modest PCs.
- An **important safety finding**: tiny models falsely claim to have fixed code. It shaped the architecture: verification before trust.
- **Validated task sets**: 12 debugging tasks proven to fail when buggy and pass when fixed, and a balanced 30-question quiz.
- An **architecture and milestone plan** that meets the spec's constraints: offline, CPU-first, privacy by default, no heavy services.

## 12. Files

```
Edu.ai/
├── docs/milestone-1-report.md        this report
├── benchmarks/
│   ├── bench_models.py                main benchmark (quality, speed, startup)
│   ├── memory_probe.py                RAM under different server settings
│   ├── repack_speed.py                speed cost of --no-repack
│   ├── analyze_failures.py            failure classification
│   ├── sandbox.py                     time-limited code runner (benchmark use)
│   ├── tasks/debug_tasks.json         12 buggy functions + tests
│   ├── tasks/concept_quiz.json        30 multiple-choice questions
│   └── results/                       per-model JSON, raw outputs, summaries
├── models/   (git-ignored)            six GGUF files, 6.8 GB
└── runtime/  (git-ignored)            llama.cpp b11780 CPU build
```

## 13. Decisions needed before Milestone 2

1. Confirm **Qwen3.5-2B as the default model** (with Granite-4.2-3B and Qwen3.5-0.8B as alternatives).
2. Confirm **how strict "4 GB" is**. If it's a hard requirement on Windows, the lite mode becomes the main path and Milestone 6 moves earlier.
3. Choose whether to **create a GitHub repository** for Edu.ai now.
