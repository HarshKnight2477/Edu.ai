"""FastAPI backend for the EduLite web interface (localhost only)."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from edulite import __version__
from edulite.conversation import DEFAULT_SYSTEM_PROMPT, Conversation
from edulite.inference import ContextOverflowError, InferenceError
from edulite.model_manager import ModelBusyError, ModelManager, models_overview
from edulite.storage import Store

STATIC_DIR = Path(__file__).parent / "static"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
MAX_MESSAGE_CHARS = 20_000


class SettingsIn(BaseModel):
    model: str | None = None
    context_tokens: int | None = None
    max_tokens: int | None = None
    threads: int | None = None
    temperature: float | None = None


class RenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _host_of(value: str) -> str:
    return (urlsplit(value if "//" in value else f"//{value}").hostname or "").lower()


def context_for(store: Store, conversation_id: int) -> Conversation:
    """The model's view of a chat. Answers that were stopped half-way are left out."""
    turns = [{"role": m.role, "content": m.content} for m in store.messages(conversation_id)
             if not (m.role == "assistant" and m.stopped)]
    return Conversation(system_prompt=DEFAULT_SYSTEM_PROMPT, turns=turns)


def create_app(manager: ModelManager, store: Store, start_model: bool = True) -> FastAPI:
    current_cancel: dict[str, threading.Event | None] = {"event": None}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if start_model:
            manager.start_in_background()
        yield
        manager.shutdown()

    app = FastAPI(title="EduLite", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        # Blocks DNS-rebinding (a foreign site resolving to 127.0.0.1) and other
        # websites sending requests to this local app from the student's browser.
        if _host_of(request.headers.get("host", "")) not in LOCAL_HOSTS:
            return JSONResponse({"detail": "EduLite only accepts requests addressed to localhost."}, status_code=400)
        origin = request.headers.get("origin")
        if origin and request.method not in ("GET", "HEAD") and _host_of(origin) not in LOCAL_HOSTS:
            return JSONResponse({"detail": "Cross-site requests are not allowed."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'")
        return response

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    # ---- status & settings -------------------------------------------------
    @app.get("/api/status")
    def status():
        return {**manager.status(), "busy": manager.generation_lock.locked(), "version": __version__,
                "models": models_overview(manager.registry, manager.config.models_dir)}

    @app.put("/api/settings")
    def update_settings(body: SettingsIn):
        try:
            restarted = manager.apply(body.model_dump())
        except ValueError as error:
            raise HTTPException(422, str(error))
        except ModelBusyError as error:
            raise HTTPException(409, str(error))
        store.save_settings(manager.settings.to_dict())
        return {**status(), "restarted": restarted}

    # ---- conversations -----------------------------------------------------
    def _conversation_or_404(conversation_id: int):
        conversation = store.get_conversation(conversation_id)
        if conversation is None:
            raise HTTPException(404, "Conversation not found")
        return conversation

    @app.get("/api/conversations")
    def list_conversations():
        return [c.__dict__ for c in store.list_conversations()]

    @app.post("/api/conversations", status_code=201)
    def create_conversation():
        return store.create_conversation().__dict__

    @app.get("/api/conversations/{conversation_id}")
    def get_conversation(conversation_id: int):
        conversation = _conversation_or_404(conversation_id)
        return {**conversation.__dict__, "messages": [m.to_dict() for m in store.messages(conversation_id)]}

    @app.patch("/api/conversations/{conversation_id}")
    def rename_conversation(conversation_id: int, body: RenameIn):
        _conversation_or_404(conversation_id)
        store.rename_conversation(conversation_id, body.title)
        return store.get_conversation(conversation_id).__dict__

    @app.delete("/api/conversations/{conversation_id}", status_code=204)
    def delete_conversation(conversation_id: int):
        if not store.delete_conversation(conversation_id):
            raise HTTPException(404, "Conversation not found")

    # ---- chatting ----------------------------------------------------------
    @app.post("/api/stop")
    def stop_generation():
        event = current_cancel["event"]
        if event is not None:
            event.set()
        return {"stopping": event is not None}

    @app.post("/api/conversations/{conversation_id}/messages")
    async def send_message(conversation_id: int, body: MessageIn, request: Request):
        _conversation_or_404(conversation_id)
        if manager.generation_lock.locked():
            raise HTTPException(409, "EduLite is already answering. Wait for it or press Stop.")
        try:
            server = manager.server  # raises if the model isn't ready
        except InferenceError as error:
            raise HTTPException(503, str(error))
        settings = manager.settings
        text = body.content.strip()

        async def events():
            # The lock is taken inside the stream so it is always released by the
            # finally block, even if the client disconnects at any point.
            if not manager.generation_lock.acquire(blocking=False):
                yield sse("error", {"message": "EduLite is already answering. Wait for it or press Stop."})
                return
            cancel = threading.Event()
            current_cancel["event"] = cancel
            stream = None
            started = time.perf_counter()
            try:
                user_message = store.add_message(conversation_id, "user", text)
                yield sse("user", user_message.to_dict())
                context = context_for(store, conversation_id)
                dropped = 0
                while True:
                    stream = server.stream_chat(context.messages(), max_tokens=settings.max_tokens,
                                                temperature=settings.temperature, cancel_event=cancel)
                    chunks = iter(stream)
                    try:
                        while True:
                            chunk = await asyncio.to_thread(next, chunks, None)
                            if chunk is None:
                                break
                            yield sse("token", {"text": chunk})
                            if await request.is_disconnected():
                                stream.cancel()  # tab closed or fetch aborted
                                break
                        break
                    except ContextOverflowError:
                        if context.drop_oldest_exchange():
                            dropped += 1
                            continue
                        store.delete_message(user_message.id)
                        yield sse("error", {"message": "That message is too long for the model's memory. "
                                                       "Try a shorter question or a larger context in Settings.",
                                            "removed_message_id": user_message.id})
                        return
                stats = {"seconds": round(time.perf_counter() - started, 1),
                         "tokens_per_second": stream.tokens_per_second,
                         "finish_reason": stream.finish_reason, "forgotten_exchanges": dropped}
                answer = store.add_message(conversation_id, "assistant", stream.text, model=settings.model,
                                           stopped=stream.cancelled, stats=stats)
                yield sse("done", answer.to_dict())
            except InferenceError as error:
                yield sse("error", {"message": str(error)})
            finally:
                if stream is not None and not cancel.is_set() and stream.finish_reason is None:
                    stream.cancel()
                current_cancel["event"] = None
                manager.generation_lock.release()

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    return app
