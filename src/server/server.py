"""FastAPI server for remote mobile access. All imports are lazy — only loaded when server starts."""

import os


def _run_translation(task_id, source_path, output_path, source_lang, target_lang, config, data_dir, task_manager):
    """Run translation in a background thread, reporting progress via WebSocket."""
    try:
        from src.agent_runtime import AgentRuntime

        llm_cfg = config.llm
        app_cfg = config.app
        app_cfg.source_lang = source_lang
        app_cfg.target_lang = target_lang
    except Exception as e:
        task_manager.update(task_id, status="failed", message=f"Init error: {e}")
        task_manager.broadcast_ws(task_id, {"type": "error", "message": str(e)})
        return

    def on_progress(stage, progress, message):
        # Check if remotely cancelled — cancel flag takes priority
        t = task_manager.get(task_id)
        if t and t.cancelled and stage not in ("cancelled", "done", "error"):
            raise InterruptedError("Translation cancelled by user")
        task_manager.update(task_id, stage=stage, progress=progress, message=message)
        task_manager.broadcast_ws(task_id, {
            "type": "progress", "stage": stage, "progress": progress, "message": message,
        })

    try:
        agent = AgentRuntime(llm_cfg, app_cfg, data_dir)
        agent.run(source_path, output_path, on_progress)
        task_manager.set_result(task_id, output_path)
        task_manager.update(task_id, status="completed", progress=100, stage="done", message="Translation complete")
        task_manager.broadcast_ws(task_id, {"type": "completed", "message": "Translation complete!"})
    except InterruptedError:
        task_manager.update(task_id, status="cancelled")
        task_manager.broadcast_ws(task_id, {"type": "cancelled"})
    except Exception as e:
        task_manager.update(task_id, status="failed", message=str(e)[:200])
        task_manager.broadcast_ws(task_id, {"type": "error", "message": str(e)[:200]})


def create_app(task_manager, config, data_dir, port):
    """Build the FastAPI application.  All heavy imports happen inside."""
    import asyncio
    from fastapi import FastAPI, UploadFile, Form, WebSocket, WebSocketDisconnect
    from fastapi.responses import FileResponse, JSONResponse

    app = FastAPI(title="AI PDF Trans", version="0.1.0")

    @app.get("/health")
    async def health():
        from .network import get_local_ips
        return {
            "status": "ok",
            "version": "0.1.0",
            "ips": get_local_ips(),
            "port": port,
        }

    @app.post("/translate")
    async def translate(
        file: UploadFile,
        source_lang: str = Form("English"),
        target_lang: str = Form("Chinese"),
    ):
        import uuid
        task_id = str(uuid.uuid4())
        task_dir = os.path.join(data_dir, "tasks", task_id)
        os.makedirs(task_dir, exist_ok=True)

        source_path = os.path.join(task_dir, "source.pdf")
        content = await file.read()
        with open(source_path, "wb") as f:
            f.write(content)

        output_path = os.path.join(task_dir, "translated.pdf")
        task_manager.create(task_id, source_path, output_path, source_lang, target_lang)
        task_manager.update(task_id, status="running", stage="agent_started", progress=5, message="Starting agent...")

        import threading
        t = threading.Thread(
            target=_run_translation,
            args=(task_id, source_path, output_path, source_lang, target_lang, config, data_dir, task_manager),
            daemon=True,
        )
        t.start()

        return {"task_id": task_id, "status": "queued"}

    @app.get("/tasks/{task_id}")
    async def get_task(task_id: str):
        task = task_manager.get(task_id)
        if task is None:
            return JSONResponse({"error": "Task not found"}, status_code=404)
        return {
            "task_id": task.task_id,
            "status": task.status,
            "stage": task.stage,
            "progress": task.progress,
            "message": task.message,
            "source_lang": task.source_lang,
            "target_lang": task.target_lang,
        }

    @app.get("/tasks/{task_id}/download")
    async def download(task_id: str):
        path = task_manager.get_result_path(task_id)
        if path is None:
            return JSONResponse({"error": "Result not available"}, status_code=404)
        filename = os.path.basename(path)
        return FileResponse(path, media_type="application/pdf", filename=filename)

    @app.delete("/tasks/{task_id}")
    async def cancel_task(task_id: str):
        task_manager.cancel(task_id)
        task_manager.broadcast_ws(task_id, {"type": "cancelled"})
        return {"status": "cancelled"}

    @app.websocket("/tasks/{task_id}/ws")
    async def ws_endpoint(websocket: WebSocket, task_id: str):
        await websocket.accept()
        import json
        import queue as _queue

        msg_queue = task_manager.add_ws(task_id, websocket)

        # Sync current state on connect — client gets the latest progress immediately
        task = task_manager.get(task_id)
        if task:
            await websocket.send_text(json.dumps({
                "type": "progress",
                "stage": task.stage or "",
                "progress": task.progress or 0,
                "message": task.message or "",
            }))

        try:
            while True:
                # Drain any queued messages first
                try:
                    msg = msg_queue.get_nowait()
                    await websocket.send_text(msg)
                    continue
                except _queue.Empty:
                    pass

                # Wait for client messages with a short timeout so we can
                        # also check the queue periodically
                try:
                    data = await asyncio.wait_for(
                        websocket.receive_text(), timeout=0.5
                    )
                    if data == "cancel":
                        task_manager.cancel(task_id)
                        await websocket.send_text(
                            json.dumps({"type": "cancelled"})
                        )
                except TimeoutError:
                    continue
        except WebSocketDisconnect:
            pass
        finally:
            task_manager.remove_ws(task_id, websocket)

    return app


def run_server(host, port, task_manager, config, data_dir):
    """Start uvicorn server (blocking — call in a daemon thread)."""
    import uvicorn
    import logging
    app = create_app(task_manager, config, data_dir, port)
    # log_config=None avoids Python 3.14+ Formatter compatibility issue
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    uvicorn.run(app, host=host, port=port, log_level="warning", log_config=None)
