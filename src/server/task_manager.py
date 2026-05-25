"""Thread-safe translation task lifecycle management."""

import queue
import threading
import time
import uuid


class TaskInfo:
    __slots__ = (
        "task_id", "status", "stage", "progress", "message",
        "source_path", "output_path", "source_lang", "target_lang",
        "created_at", "completed_at", "_cancel_flag",
    )

    def __init__(self, task_id, source_path, output_path, source_lang, target_lang):
        self.task_id = task_id
        self.status = "queued"
        self.stage = ""
        self.progress = 0
        self.message = ""
        self.source_path = source_path
        self.output_path = output_path
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.created_at = time.time()
        self.completed_at = None
        self._cancel_flag = threading.Event()

    def cancel(self):
        self._cancel_flag.set()

    @property
    def cancelled(self):
        return self._cancel_flag.is_set()


class TaskManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._tasks = {}
        # task_id -> [(websocket, queue.Queue)]
        self._ws_connections = {}

    def create(self, task_id, source_path, output_path, source_lang, target_lang):
        task = TaskInfo(task_id, source_path, output_path, source_lang, target_lang)
        with self._lock:
            self._tasks[task_id] = task
            self._ws_connections[task_id] = []
        return task

    def get(self, task_id):
        with self._lock:
            return self._tasks.get(task_id)

    def get_active_task_info(self):
        """Return the first running task, or the most recently completed/failed/cancelled task.
        Used by the desktop GUI to show remote task progress.
        Returning terminal-state tasks ensures the UI doesn't freeze on the last 'running' update."""
        with self._lock:
            terminal = None
            for task in self._tasks.values():
                if task.status == "running":
                    return task
                if task.status in ("completed", "failed", "cancelled"):
                    if terminal is None or (
                        task.completed_at
                        and terminal.completed_at
                        and task.completed_at > terminal.completed_at
                    ):
                        terminal = task
            return terminal

    def update(self, task_id, **kwargs):
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return
            for k, v in kwargs.items():
                if hasattr(task, k):
                    setattr(task, k, v)

    def cancel(self, task_id):
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.cancel()
                task.status = "cancelled"

    def set_result(self, task_id, pdf_path):
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.output_path = pdf_path
                task.status = "completed"
                task.completed_at = time.time()

    def get_result_path(self, task_id):
        with self._lock:
            task = self._tasks.get(task_id)
            if task and task.status == "completed":
                return task.output_path
            return None

    def add_ws(self, task_id, ws):
        """Register a WebSocket connection. Returns a queue.Queue for sending messages."""
        q = queue.Queue()
        with self._lock:
            if task_id not in self._ws_connections:
                self._ws_connections[task_id] = []
            self._ws_connections[task_id].append((ws, q))
        return q

    def remove_ws(self, task_id, ws):
        with self._lock:
            if task_id in self._ws_connections:
                self._ws_connections[task_id] = [
                    (w, q) for w, q in self._ws_connections[task_id] if w is not ws
                ]

    def broadcast_ws(self, task_id, message):
        """Put a message on every connection's queue for this task.
        Called from sync threads — the actual ws.send_text happens on the event loop."""
        import json
        payload = json.dumps(message)
        dead_ws = []
        with self._lock:
            connections = list(self._ws_connections.get(task_id, []))
        for ws, q in connections:
            try:
                q.put_nowait(payload)
            except Exception:
                dead_ws.append(ws)
        if dead_ws:
            with self._lock:
                self._ws_connections[task_id] = [
                    (w, q) for w, q in self._ws_connections[task_id] if w not in dead_ws
                ]
