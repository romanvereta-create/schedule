"""Single-process production entry point; python bot.py remains the command."""
import os
import signal
import threading
import time
from telegram.request import HTTPXRequest
from contextlib import contextmanager
from pathlib import Path


class TelegramDiagnostics:
    """Only operation names, timings and error classes; never tokens or payloads."""
    def __init__(self):
        self.lock = threading.Lock()
        self.operations = {}
        self.start_stage = "not_received"

    def record(self, operation, state):
        if operation not in {"getMe", "getUpdates", "sendMessage", "deleteWebhook"}:
            return
        with self.lock:
            item = self.operations.setdefault(operation, {"attempts": 0})
            if state == "pending":
                item["attempts"] += 1
            item.update(state=state, changed=time.monotonic())
        if state not in {"pending", "ok"}:
            print(f"TEMLI Telegram {operation}: {state}", flush=True)

    def stage(self, value):
        with self.lock:
            self.start_stage = value
        print(f"TEMLI /start: {value}", flush=True)

    def snapshot(self):
        with self.lock:
            return {
                "start_stage": self.start_stage,
                "requests": {name: {
                    "state": item["state"], "attempts": item["attempts"],
                    "state_age_seconds": round(time.monotonic() - item["changed"], 1),
                } for name, item in self.operations.items()},
            }


class ObservedTelegramRequest(HTTPXRequest):
    def __init__(self, diagnostics, **kwargs):
        self.diagnostics = diagnostics
        super().__init__(**kwargs)

    async def do_request(self, url, method, **kwargs):
        operation = url.rsplit("/", 1)[-1]
        self.diagnostics.record(operation, "pending")
        try:
            result = await super().do_request(url=url, method=method, **kwargs)
        except Exception as error:
            self.diagnostics.record(operation, type(error).__name__)
            raise
        code = result[0]
        self.diagnostics.record(operation, "ok" if code == 200 else f"http_{code}")
        return result


@contextmanager
def single_instance(root):
    with open(Path(root) / ".temli-runtime.lock", "a+b") as handle:
        if os.name == "nt":
            import msvcrt
            if handle.seek(0, 2) == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def make_server(host):
    if host.ALLOW_UNAUTHENTICATED:
        raise RuntimeError("Production requires ALLOW_UNAUTHENTICATED=false")
    from waitress import create_server
    return create_server(host.flask_app, host="0.0.0.0",
                         port=int(os.getenv("PORT", "8080")), threads=4,
                         max_request_body_size=6 * 1024 * 1024,
                         channel_timeout=120, expose_tracebacks=False)


def run(host):
    if not host.TOKEN:
        raise RuntimeError("SCHEDULE_BOT_TOKEN is required")
    if host.ALLOW_UNAUTHENTICATED:
        raise RuntimeError("Production requires ALLOW_UNAUTHENTICATED=false")
    bootstrap_retries = int(os.getenv("TELEGRAM_BOOTSTRAP_RETRIES", "-1"))
    if bootstrap_retries < -1 or bootstrap_retries > 100:
        raise RuntimeError("TELEGRAM_BOOTSTRAP_RETRIES must be -1 or between 0 and 100")
    remote = getattr(host, "REMOTE_STORAGE", None)
    replica_dir = None
    replica_settings = None
    if remote is not None:
        # Fail before starting Telegram polling if the Russian storage cannot
        # be reached or authenticated.
        remote.read_json("teacher_registry.json", {})
        from backup_replica import configured_replica_dir, replica_settings as read_replica_settings
        replica_dir = configured_replica_dir()
        if replica_dir is not None:
            replica_settings = read_replica_settings()
    from automatic_backup import start_worker
    with single_instance(host.BASE_DIR):
        os.makedirs(host.RECEIPT_ASSETS_DIR, exist_ok=True)
        os.makedirs(host.RECEIPTS_DIR, exist_ok=True)
        host.init_book()
        diagnostics = TelegramDiagnostics()
        host.TELEGRAM_DIAGNOSTICS = diagnostics
        app = (
            host.Application.builder()
            .token(host.TOKEN)
            .request(ObservedTelegramRequest(diagnostics, connect_timeout=30,
                     read_timeout=30, write_timeout=30, pool_timeout=30))
            .get_updates_request(ObservedTelegramRequest(diagnostics, connection_pool_size=1,
                     connect_timeout=30, read_timeout=45, write_timeout=30, pool_timeout=30))
            .post_init(host.post_init)
            .post_stop(host.post_stop)
            .build()
        )
        app.add_handler(host.CommandHandler("start", host.start))
        server = make_server(host)  # Bind before starting background tasks.
        stopping = threading.Event()
        def serve():
            try:
                server.run()
            finally:
                if not stopping.is_set():
                    # A dead HTTP loop must not leave a seemingly healthy polling process.
                    os.kill(os.getpid(), signal.SIGTERM)
        thread = threading.Thread(target=serve, name="temli-http", daemon=True)
        replica_stop = replica_thread = None
        try:
            thread.start()
            if remote is None:
                start_worker(host)
            else:
                print("TEMLI automatic backup: delegated to remote storage", flush=True)
                if replica_dir is not None:
                    from backup_replica import start_worker as start_replica_worker
                    replica_stop, replica_thread = start_replica_worker(
                        remote, replica_dir,
                        interval=replica_settings["interval"],
                        retention=replica_settings["retention"],
                    )
                    print("TEMLI backup replica: enabled", flush=True)
            print("TEMLI production: Waitress; 1 process, 4 HTTP threads", flush=True)
            print("TEMLI storage: " + host.BASE_DIR, flush=True)
            print("TEMLI Telegram bootstrap retries: " + str(bootstrap_retries), flush=True)
            app.run_polling(bootstrap_retries=bootstrap_retries)
        finally:
            stopping.set()
            if replica_stop is not None:
                replica_stop.set()
            if replica_thread is not None:
                replica_thread.join(timeout=5)
            server.close()
            server.task_dispatcher.shutdown()
            thread.join(timeout=5)
