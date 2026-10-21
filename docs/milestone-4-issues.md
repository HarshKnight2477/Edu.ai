# Milestone 4 — Problems, Remediation and Results

Date: 2026-10-22 · Versions compared: **m4-v1** (original) → **m4-v2** (remediated prompts) → **m4-v3** (+ hint-mode output check) → **m4-v4** (+ explicit debug explanation length) → **m4-v6** (+ deterministic one-sentence trim)
**Verdict: Milestone 4 Complete.** On both models, tutor + notes meets every acceptance criterion: quiz comparable or better, debug fixes equal to the baseline, the requested debug format followed in 12/12 answers, the hint policy at 100%, and 171 tests passing. Remaining limits, mainly the lite model's weak debugging, are listed in section 7. Details in section 6.

---

## 1. Problems identified (from the m4-v1 evaluation)

| # | Problem | Measured on Qwen3.5-2B, m4-v1 |
|---|---|---|
| P1 | The tutor prompt alone lowered quiz accuracy | 91.7% → 80.0% |
| P2 | The tutor prompt alone lowered debug success; the template overrode the requested format | 12/12 → 9/12 |
| P3 | Notes slightly increased homework-solution leaks | 1 → 2 of 10 violations |
| P4 | The quiz grader could misread verbose replies (first standalone A–D) | Suspected |
| P5 | Notes recovered most of the loss, but didn't beat the baseline | 88.3% quiz, 12/12 debug |

## 2. Root causes found (by inspecting code and saved answers)

- **P1, wrong mode:** 9 of the 60 quiz questions were auto-routed to **Debug** mode. The old detector fired on isolated words like `error`, `exception`, `KeyError` or `bug`, mostly found in *answer options* ("It raises an error") or in conceptual questions ("Why is `def add(item, items=[])` a common bug?"). It ignored the message's structure.
- **P1/P2, template over request:** the explain and debug templates prescribed fixed structures (analogy, four debugging steps, explanation before code). The model followed them over the student's explicit format request, producing long essays.
- **P2, analogy over analysis:** the beginner level demanded "an everyday analogy" every time. In one case the analogy replaced actually tracing the code: the mutable-default bug was "explained" with a bucket and misdiagnosed.
- **P4, grader: not a cause after all.** The strict grader (section 3) re-scored the saved m4-v1 answers. For the default model the scores were **identical, with 100% coverage**: all 180 replies started with the chosen letter. For the lite model the old grader *was* guessing: its m4-v1 tutor run had **22 unparseable replies**, and its accuracy drops from 51.7% to 48.3% under strict grading.
- **P3, leaks are mostly model behaviour, not note content.** In m4-v2, after code was removed from notes in hint mode, the remaining leaks still happen. The model writes "Try writing this code:" or "Here is a simple hint:" followed by an essentially complete function, even when the retrieved notes contain no code (bubble sort) or are irrelevant (file I/O notes for a vowel-counting exercise).

## 3. Changes implemented

| File | Change | Addresses |
|---|---|---|
| `eduai/tutor/prompts.py` | **Mode detection rewritten.** Debug now needs evidence: a traceback or error line (`TypeError: …`), code together with a reported problem, or an explicit request about the student's own code ("fix my…", "why does my…", "what's wrong with this…"). Conceptual questions and code-explanation requests go to Explain. Explicit hint, quiz and full-solution requests win first. | P1 |
| `eduai/tutor/prompts.py` | **Format priority:** a new rule right after the persona says that the student's explicit format or length request overrides the teaching steps. | P2 |
| `eduai/tutor/prompts.py` | **Debug template is code-first:** trace the code with the failing input, show the smallest fix, then briefly explain; ask for missing code. No numbered sections, no analogy. **Beginner level:** "use an analogy only if it makes the idea clearer". **Explain:** no mandatory headings; short answers to factual questions. | P2 |
| `eduai/tutor/prompts.py` | **Hint mode and notes:** code blocks in retrieved notes that define a function or class, or run 3+ lines, are replaced by a placeholder, while prose, inline code and 1–2 line snippets stay. The notes are introduced as "for explaining ideas, not for writing the solution". Explain and Debug still get full code examples. The notes have no metadata separating worked solutions from concepts, so this structural rule is the documented fallback. | P3 |
| `eduai/tutor/prompts.py` | `PROMPT_VERSION = "m4-v2"`, recorded in every evaluation result. | Reproducibility |
| `benchmarks/grading.py` (new) | **Strict answer extraction**, separate from scoring: accepts a bare letter, a leading option label ("C. …"), or an explicit label ("Answer: C", "Option C"). Anything else, or conflicting labels, is *unparseable*. Reports correct / incorrect / unparseable / coverage / accuracy-on-parseable, and Wilson 95% intervals. | P4 |
| `benchmarks/regrade_quiz.py` (new) | Re-scores saved replies without new inference. | P4 |
| `benchmarks/eval_tutoring.py` | v2: strict grading; debug **format check** (one code block, then ≤2 sentences / ≤400 characters) and cut-off tracking; the **extended homework benchmark**; a diagnostic for solutions written outside code blocks; metadata (prompt version, model file, llama.cpp build, decoding, task counts); per-request latency and server peak RAM. **The baseline prompt is unchanged.** | P2–P5, methodology |
| `benchmarks/tasks/hint_tasks_extended.json` (new) | 10 extra homework cases in 5 categories: notes with the exact solution, notes with a similar solution, concept-only notes, explicit "give me the full solution" (a solution is then *expected*), and second-turn "next hint". | P3 |
| `tests/test_tutor.py`, `tests/test_grading.py` | 49 new regression tests: conceptual questions mentioning errors → Explain, real bugs / tracebacks / explicit debug requests → Debug, explicit intent wins, format-priority placement, the code-first debug template, note redaction (worked solutions removed, concepts kept, Explain keeps code), and strict grading edge cases. | All |
| `benchmarks/results/tutoring_m4-v1_*` | The original results, renamed (kept, not overwritten), plus `.regraded.json` files. New results are in `tutoring_m4-v2_*`. | Reproducibility |

Not changed: model configurations, the inference layer, retrieval ranking, the web/CLI interfaces, the baseline prompt, and every task's expected answers. No task IDs, answers or special cases are hard-coded.

### m4-v3: hint-mode output check (added after the v2 results)

v2 showed that the 2B model still presented complete functions as "hints" even when the notes contained no code, so prompt wording alone wasn't enough.

| File | Change |
|---|---|
| `eduai/tutor/guard.py` (new) | `HintGuard`, a streaming filter used only in hint mode. Prose passes through immediately; each fenced code block is held until it closes. A block that defines a function, returns a value and has 3+ code lines (the shape of a complete solution) is replaced by a note offering the full solution on request. Skeletons, syntax snippets and pseudo-code are kept. |
| `eduai/web/app.py`, `eduai/cli.py` | Hint-mode answers go through the guard; **the saved message is what the student saw**; stats record `solutions_withheld`. |
| `benchmarks/eval_tutoring.py` | The same guard applied in the tutor configurations when the mode is hint (as in the product); `--tasks hint` re-runs only the homework sets. |
| `tests/test_guard.py`, `tests/test_web.py`, `tests/test_cli.py`, `tests/fake_llama_server.py` | 14 new tests: solution shape, prose kept, harmless code kept, identical results for any chunk size, prose released immediately while code is held, an unclosed block judged at the end, end-to-end checks that the solution never reaches the browser or terminal in hint mode, and that Explain mode is untouched. The fake server can now stream a given text. |

### m4-v4: explicit debug explanation length

| File | Change |
|---|---|
| `eduai/tutor/prompts.py` | The debug template now says: "Then, **in one or two sentences**, say what caused the bug and why the fix works (**exactly one sentence if the student asks for one**)", instead of "briefly". `PROMPT_VERSION = "m4-v4"`. |
| `benchmarks/eval_tutoring.py` | `--tasks debug` re-runs only the debugging set. |

Only debug mode's wording changed, so the quiz (Explain mode) and homework (Hint mode) results from v2/v3 still apply.

### m4-v5 / m4-v6: deterministic one-sentence trim

v4 showed that wording alone doesn't make the 2B model keep to one sentence, so the format became a guaranteed property, like the hint policy.

| File | Change |
|---|---|
| `eduai/tutor/guard.py` | `OneSentenceGuard` + `select_guard()`. Active only when the student's latest message explicitly asks for one sentence ("one sentence", "a single sentence", "1 sentence"). With a code-block request, the answer becomes the first code block plus one sentence of explanation; otherwise, the first sentence. The sentence splitter doesn't break on decimals ("1.8") or "e.g.". The whole answer is buffered and shown when complete, since such answers are short. Hint mode keeps priority (the hint guard runs instead). **m4-v6 fix:** if nothing follows the code, the first sentence written *before* it is used. v5 had dropped the explanation entirely for the lite model, which explains first (see results). |
| `eduai/web/app.py`, `eduai/cli.py`, `benchmarks/eval_tutoring.py` | All three use the same `select_guard()`, so the evaluation measures exactly what students see. Stats record `trimmed_to_one_sentence`. The baseline configuration is never trimmed. |
| `tests/test_guard.py`, `tests/test_web.py` | 13 new tests: request detection, sentence splitting, trim with and without code, the fallback to an explanation before the code, buffering, selector priority, and end-to-end web trimming only when one sentence is explicitly requested. |

Why quiz and debug weren't re-run for v3: hint mode is never selected for them (all 60 quiz prompts → Explain, all 12 debug prompts → Debug; verified), and the guard is only active in hint mode. So their v2 results also hold for v3.

## 4. Tests run

- **Unit and integration suite: 158 passed** (95 before this remediation + 49 for v2 + 14 for the v3 guard). That covers all earlier milestones, the API and UI logic, the real-model end-to-end tests, and the new regression tests.
- **Strict re-grading** of both m4-v1 result files (no inference).
- **Full m4-v2 evaluation** on both models: 3 configurations × (60 quiz + 12 debug + 10 hint + 10 extended hint), with the same tasks, greedy decoding, 8 threads and llama.cpp b11780 as m4-v1. All 6 runs completed.
- **m4-v5 and m4-v6 debug evaluations** (`--tasks debug`) on both models, all 3 configurations (`tutoring_m4-v6_<model>_debug.json`; v5 is kept but superseded). **Final suite: 171 passed.**
- **m4-v4 debug evaluation** (`--tasks debug`) on both models, all 3 configurations, with the baseline re-run under the same conditions. Completed (`tutoring_m4-v4_<model>_debug.json`). The suite was re-run after the change: 158 passed.
- **m4-v3 homework evaluation** (`--tasks hint`) on both models: 3 configurations × (10 hint + 10 extended hint). All 6 runs completed (`tutoring_m4-v3_<model>_hint.json`).

## 5. Measured results

### Qwen3.5-2B (default)

| Metric | Baseline (v1 → v2) | Tutor v1 → **v2** | Tutor + notes v1 → **v2** |
|---|---|---|---|
| Quiz accuracy, strict (60) | 91.7% → 91.7% | 80.0% → **86.7%** | 88.3% → **90.0%** |
| Quiz 95% interval / coverage | 82–96% / 100% | 76–93% / 100% | 80–95% / 100% |
| Debug fixed (12, unit tests) | 12 → 12 | 9 → **12** | 12 → **12** |
| Debug format followed (12) | — / 11 | — / **3** | — / **7** |
| Debug: unchanged-code answers | 0 | 0 | 0 |
| Hint violations, original 10 | 10 → 10 | 1 → **1** | 2 → **2** |
| Hint policy followed | 0% | **90%** | **80%** |
| Extended homework cases handled correctly (10) | 3 | **10** | **8** |
| Median seconds: quiz / debug / hint | 0.47 / 4.9 / 13.8 | 1.01 / 7.1 / 7.5 | 2.81 / 8.6 / 12.3 |
| Server peak RAM | 1,451 MB | 1,456 MB | 1,478 MB |

### Qwen3.5-0.8B (lite)

| Metric | Baseline | Tutor v1 → **v2** | Tutor + notes v1 → **v2** |
|---|---|---|---|
| Quiz accuracy, strict (60) | 66.7% (coverage 93%) | 48.3% → **51.7%** (coverage 73%) | 73.3% → **78.3%** (coverage 97%) |
| Debug fixed (12) | 5 | 4 → **4** | 6 → **4** |
| Debug: unchanged-code answers | 5 | 6 → **5** | 2 → **7** |
| Hint violations, original 10 | 5 | 3 → **4** | 2 → **4** |
| Extended homework cases handled correctly (10) | 4 | **9** | **5** |
| Server peak RAM | 1,026 MB | 1,029 MB | 1,039 MB |

v1 figures use the strict grader; v1 debug and hint numbers come from the m4-v1 run. Small samples: one debug task or hint case is 8–10 points, so changes of one or two items are within noise.

### Homework policy with the output check (m4-v3)

| | Default baseline | Default tutor | **Default tutor + notes** | Lite baseline | Lite tutor | **Lite tutor + notes** |
|---|---|---|---|---|---|---|
| Violations, original 10 (v2 → **v3**) | 10 → 10 | 1 → **1** | 2 → **0** | 5 → 5 | 4 → **0** | 4 → **0** |
| Policy followed | 0% | 90% | **100%** | 50% | **100%** | **100%** |
| Extended cases handled correctly (10) | 3 | 10 | **9** | 4 | **10** | **8** |
| Solution blocks withheld by the guard (20 answers) | 0 | 2 | 3 | 0 | 7 | 10 |
| Median hint answer time | 13.8 s | 6.7 s | 10.9 s | 6.2 s | 4.7 s | 7.0 s |

- **Uncertainty:** with 10 cases, 0 violations gives a 95% interval for the true violation rate of 0–28%; 1 violation gives 2–40%.
- **Guidance kept:** after the guard, every hint answer still contained substantial prose, a median of 126–196 words, with none under 25 words. The guard removes solutions, not the help.
- **Remaining v3 failures:**
  - **Default tutor (no notes), hint-09:** a **2-line** solution (`def …:` + `return (c * 1.8) + 32`) passed, because the guard only removes blocks of 3+ code lines so that tiny syntax examples survive. This is a known limit of the rule.
  - **hx-explicit-01 (both models): an evaluation artifact.** The model gave a correct solution named `find_largest` instead of the requested `largest`.
  - **hx-explicit-02 (lite + notes):** asked for the full code, the model wrote an incorrect `vowel_count`. This is a capability issue; the guard isn't involved, since explicit requests use Write-code mode.

### Debugging with explicit explanation length (m4-v4)

| | Default baseline | Default tutor | **Default tutor + notes** | Lite baseline | Lite tutor | **Lite tutor + notes** |
|---|---|---|---|---|---|---|
| Fixed, unit tests (v2 → **v4**) | 12 → 12 | 12 → **11** | 12 → **12** | 5 → 5 | 4 → **2** | 4 → **5** |
| Format followed (v2 → **v4**) | 11 → 11 | 3 → **9** | 7 → **9** | 0 → 0 | 1 → **0** | 2 → **2** |
| Unchanged-code answers | 0 | 0 | 0 | 5 | 6 | 6 |
| Answers cut off at the token limit | 0 | 0 | 0 | 0 | 0 | 0 |
| Median seconds per debug answer | 5.6 | 7.3 | 8.4 | 3.1 | 3.1 | 4.0 |

- **Default model, remaining format misses (tutor + notes: debug-09, -11, -12):** all fixes pass the tests; all are code-first with a single block (one, debug-11 in the no-notes run, starts with a short sentence). The explanation runs to **3–4 sentences (299–427 characters)** instead of the requested one. The model shortens its explanations when told the length, but doesn't reliably hold to one sentence.
- **Default tutor (no notes), debug-12 regression: a genuine reasoning error.** It de-duplicated correctly (`sorted(set(nums))`) but returned index `[1]` (the second *smallest*) instead of `[-2]`. Single-run greedy decoding, so one task flipping is within run-to-run sensitivity to prompt wording.
- **Lite model:** tutor + notes now matches its own baseline on fixes (5/12 each) and follows the format slightly more often (2/12 vs 0/12). The no-notes tutor fell to 2/12. As before, most failures repeat the buggy code unchanged: a capability limit.
- **Uncertainty:** 9/12 → 95% interval 47–91%; 11/12 → 65–99%. The baseline/tutor + notes format difference (2 tasks) is not statistically distinguishable at n = 12, but it is a measured shortfall, not equality.

### Debugging with the one-sentence trim (m4-v6, final)

| | Default baseline | Default tutor | **Default tutor + notes** | Lite baseline | Lite tutor | **Lite tutor + notes** |
|---|---|---|---|---|---|---|
| Fixed, unit tests | 12/12 | 11/12 | **12/12** | 5/12 | 2/12 | **5/12** |
| Format followed (code block, then one sentence) | 11/12 | 12/12 | **12/12** | 0/12 | 12/12 | **12/12** |
| Answers with no explanation at all | 0 | 0 | 0 | 5 | 0 | **0** |
| Answers trimmed | — | 12 | 9 | — | 12 | 10 |
| Median seconds per debug answer | 4.9 | 7.0 | 8.5 | 3.4 | 3.3 | 4.3 |

- **The trim never changes the code**, so the fix rates are the same as without it (default 12/12; lite tutor + notes 5/12 in both v5 and v6).
- **v5 → v6, lite model:** format followed rose from 3/12 to 12/12, and answers with no explanation fell from 9 to 0. The fallback fixed a real problem: in v5, students would have received bare code.
- **Quality of the kept sentence (default, tutor + notes, read by hand):**
  - **9 of 12 are precise diagnoses.** For example "starting the loop at index 1 instead of 0…" and "`while low < high` … skips the final element when the list has only one item".
  - **2 are vague but not false.** debug-09 says "using the `+=` operator to add to a dictionary value", where the real cause is a missing key. debug-06 says "the order of the `if` statements".
  - **1 is wrong although the fix passes.** debug-12 claims "`sorted(nums)` sorts the list in place and returns `None`"; the real cause is duplicate values. The trim keeps the model's first sentence and can't correct a misdiagnosis.

### Remaining failures, analysed (v2 run)

**Default model, hint violations (tutor + notes):**
- **hint-02 (count vowels):** the model says "Try writing this code:" and gives a working function. The retrieved notes were irrelevant (file I/O, C arrays, text generation), which is also a retrieval weakness for this query.
- **hint-05 (sum digits):** "Try this:", followed by a working `while n > 0` loop. The notes contained no matching code.
- **Diagnosis:** the leaks come from the model labelling complete code as a "hint", not from note content. The no-notes tutor leaked once (hint-09, a one-line formula, where any concrete hint is nearly the solution).

**Default model, extended cases:**
- **hx-concept-01 (bubble sort): a real leak.** "Step 3: The Code — here is a simple hint" contains the full function. The notes for bubble sort have no code.
- **hx-explicit-01: an evaluation artifact, not a policy failure.** The student asked for `largest(nums)`; the model gave a correct solution named `find_largest`, so the hidden tests couldn't call it. It's left as measured, not re-scored.

**Default model, debug format:** all fixes passed the unit tests. Every format miss was **code-first with exactly one code block**, followed by 2–4 sentences (250–400 characters) instead of one. The fix order is right; the explanation is just longer than asked.

**Lite model, debugging (tutor + notes, 8 failures):**

| Task | Diagnosis given | Diagnosis correct? | Fix | Passed tests | Format followed |
|---|---|---|---|---|---|
| debug-04 vowels | Vague: says characters aren't checked properly | No (case sensitivity is the cause) | Code unchanged | No | No |
| debug-05 max | `max_val = 0` ignores negatives | **Yes** | Code unchanged | No | No |
| debug-06 fizzbuzz | Describes the `elif` order, but traces the conditions wrongly | Partly | Code unchanged | No | No |
| debug-07 binary search | `while low < high` skips one-element lists | **Yes** | Code unchanged | No | No |
| debug-08 remove duplicates | List modified while iterating | **Yes** | Code unchanged | No | No |
| debug-09 word frequencies | Blames `split()` | No (missing key initialisation) | Code unchanged | No | Yes |
| debug-10 mutable default | Shared default list | **Yes** | Removed the parameter, which breaks `append_item('c', ['x'])` | No | No |
| debug-12 second largest | Contradicts itself and says the answer is 5 | No | Code unchanged | No | No |

These are **genuine model limitations, not formatting or evaluation errors**. The 0.8B model often explains the cause correctly but can't edit the code, repeating the bug unchanged in 7 of 8 failures. This matches the Milestone 1 finding, and prompts can't fix it.

## 6. Acceptance criteria

| Criterion | Default (2B) | Met? | Lite (0.8B) | Met? |
|---|---|---|---|---|
| Quiz: tutor + notes comparable to the baseline | 90.0% vs 91.7%, a **−1.7-point** difference with heavily overlapping 95% intervals (80–95% vs 82–96%). Not proof of equivalence; the sample is 60 questions | ✅ Comparable | 78.3% vs 66.7% (**+11.6 points**) | ✅ Better |
| Debug: tutor + notes matches the baseline without sacrificing format | v6: **12/12 = baseline; format 12/12** (baseline 11/12) | ✅ | v6: **5/12 = baseline; format 12/12** (baseline 0/12) | ✅ Relative to its baseline (absolute level low) |
| Hint policy ≥ 90% (10 cases) | v3: tutor + notes **100% (0 violations)**; tutor alone 90% (1) | ✅ | v3: **100% (0 violations)** | ✅ |
| All tests pass | 171/171 | ✅ | — | ✅ |
| Resources recorded, no GPU needed | Peak RAM +27 MB with notes; notes add ~2 s of prompt reading per quiz question (median 2.8 s vs 0.5 s) | ✅ | +13 MB | ✅ |

**Verdict: Milestone 4 Complete.** Measured on the final configuration (tutor + notes, m4-v6, with the hint and one-sentence output checks):
- **Default model:** quiz 90.0% vs baseline 91.7% (−1.7 points, overlapping intervals); debug 12/12 = baseline with the format followed 12/12; hint policy 100%.
- **Lite model:** quiz 78.3% vs 66.7% (+11.6 points); debug 5/12 = baseline with the format followed 12/12; hint policy 100%.
- **Resolved:** P1 (mode detection), P2 (format), P3 (hint leaks), P4 (grading). P5 is resolved in the sense the criteria require: notes make the tutor comparable to the baseline on the default model and better on lite.
- **Caveats:**
  - The samples are small: 12 debug tasks and 10 hint cases.
  - The lite model's absolute debugging level stays low: 5/12, often returning code unchanged.
  - The one-sentence trim can keep a model sentence that is vague or, once in 12 answers, wrong.

## 7. Outstanding issues and next steps

1. **The lite model's debugging (5/12)** is a capability limit. Present lite mode as concept-focused and route code fixes through the Milestone 7 sandboxed verifier (run the student's tests before calling anything "fixed").
2. **Explanation accuracy after the trim:** the trim guarantees format, not truth. One of 12 kept sentences was wrong (debug-12). The Milestone 7 verifier and Milestone 8's human review should check explanations, not just fixes.
3. **Hint guard limit:** solutions of 1–2 code lines pass (default tutor without notes, hint-09). If that matters, the guard could also remove any block that defines the function named in the student's exercise.
4. **Retrieval for some exercise phrasings** returns irrelevant notes (hint-02 in v2). The relative cutoff could be tightened, or notes skipped in hint mode when no section scores above a higher threshold.
5. **Measurement:** extended case hx-explicit-01 fails on a function-name mismatch (`find_largest` vs `largest`). Exercises should state that the given function name must be used, or the scorer should report naming mismatches separately.
6. **Latency:** notes add about 2–3 seconds of prompt reading per answer (median quiz 2.8 s vs 0.5 s; debug 8.5 s vs 4.9 s). Answers trimmed to one sentence and hint code blocks are shown when complete rather than streamed.
7. **Not yet done:** a manual browser check of the new UI elements (mode picker, mode and source labels, level and notes settings) with the real model. Their logic is covered by API tests.
