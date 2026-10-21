# EduLite

A lightweight, offline AI tutor for programming and AI, designed for low-end PCs without a GPU.

**Status:** Milestone 3 (web chat interface) complete.
- [Milestone 1 report](docs/milestone-1-report.md): model selection and architecture
- [Milestone 2 report](docs/milestone-2-report.md): inference engine, tests and measurements
- [Milestone 3 report](docs/milestone-3-report.md): web interface, chat history, settings

## Quick start (Windows)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
python -m edulite --list-models
python -m edulite --web           # web interface at http://127.0.0.1:8770
python -m edulite                 # terminal chat
```

Needs llama.cpp CPU build b11780 in `runtime/llama-cpu/` and the GGUF models in `models/`. `--list-models` shows each model's download link and whether it's installed.

| Model | Key | RAM (measured) | Use |
|---|---|---|---|
| Qwen3.5-2B Q4_K_M | `default` | ~1.4 GB | Balanced default |
| Qwen3.5-0.8B Q4_0 | `lite` | ~1.0 GB | Low-memory PCs |
| Granite-4.2-3B Q4_K_M | `quality` | ~2.4 GB | Best answers, slower |

Settings can be set with flags (`--threads`, `--ctx`, `--max-tokens`, `--port`) or environment variables (`EDULITE_MODEL`, `EDULITE_THREADS`, `EDULITE_CTX`, `EDULITE_MAX_TOKENS`, `EDULITE_PORT`).

## Tests

```bash
python -m pytest        # 58 tests; the real-model tests are skipped if the runtime/model aren't installed
```

## Benchmarks

`benchmarks/` holds the Milestone 1 model comparison and `measure_inference.py`, which measures the Milestone 2 engine.
