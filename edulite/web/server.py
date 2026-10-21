"""Start the EduLite web interface on this computer.

    python -m edulite --web             # opens http://127.0.0.1:8770 in your browser
    python -m edulite --web --no-browser --web-port 9000
"""

from __future__ import annotations

import logging
import threading
import webbrowser

import uvicorn

from edulite.config import REGISTRY, InferenceConfig, model_status
from edulite.model_manager import ModelManager, validate_settings
from edulite.storage import Store
from edulite.web.app import create_app

logger = logging.getLogger("edulite.web")
DEFAULT_WEB_PORT = 8770


def restore_settings(config: InferenceConfig, store: Store) -> tuple[InferenceConfig, dict]:
    """Apply settings saved from the web UI, ignoring any that are no longer valid.

    Returns the inference config and the tutoring settings (level, use_notes).
    """
    tutoring = {"level": "beginner", "use_notes": True}
    saved = store.get_settings()
    if not saved:
        return config, tutoring
    merged = {"model": config.model.key, "context_tokens": config.context_tokens,
              "max_tokens": config.max_tokens, "threads": config.threads,
              "temperature": config.temperature, **tutoring, **saved}
    try:
        validate_settings(merged)
    except (ValueError, KeyError) as error:
        logger.warning("Ignoring saved settings: %s", error)
        return config, tutoring
    config = config.with_overrides(model=REGISTRY[merged["model"]], context_tokens=merged["context_tokens"],
                                   max_tokens=merged["max_tokens"], threads=merged["threads"],
                                   temperature=merged["temperature"])
    return config, {"level": merged["level"], "use_notes": merged["use_notes"]}


def run(config: InferenceConfig, port: int = DEFAULT_WEB_PORT, open_browser: bool = True,
        explicit_model: bool = False) -> None:
    store = Store()
    tutoring = {"level": "beginner", "use_notes": True}
    if not explicit_model:
        config, tutoring = restore_settings(config, store)
    if not model_status(config.model).installed:
        fallback = next((s for s in REGISTRY.values() if model_status(s).installed), None)
        if fallback is None:
            raise SystemExit("No EduLite model is installed. Run: python -m edulite --list-models")
        config = config.with_overrides(model=fallback)
    app = create_app(ModelManager(config, **tutoring), store)
    url = f"http://127.0.0.1:{port}"
    print(f"EduLite is starting at {url}  (press Ctrl+C here to stop)")
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    try:
        # 127.0.0.1 only: the app is never reachable from other computers.
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    finally:
        store.close()
