"""Single-process production entry point; python bot.py remains the command."""
import os
import signal
import threading
from contextlib import contextmanager
from pathlib import Path


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
    remote = getattr(host, "REMOTE_STORAGE", None)
    if remote is not None:
        # Fail before starting Telegram polling if the Russian storage cannot
        # be reached or authenticated.
        remote.read_json("teacher_registry.json", {})
    from automatic_backup import start_worker
    with single_instance(host.BASE_DIR):
        os.makedirs(host.RECEIPT_ASSETS_DIR, exist_ok=True)
        os.makedirs(host.RECEIPTS_DIR, exist_ok=True)
        host.init_book()
        app = host.Application.builder().token(host.TOKEN).post_init(host.post_init).post_stop(host.post_stop).build()
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
        try:
            thread.start()
            if remote is None:
                start_worker(host)
            else:
                print("TEMLI automatic backup: delegated to remote storage", flush=True)
            print("TEMLI production: Waitress; 1 process, 4 HTTP threads", flush=True)
            print("TEMLI storage: " + host.BASE_DIR, flush=True)
            app.run_polling()
        finally:
            stopping.set()
            server.close()
            server.task_dispatcher.shutdown()
            thread.join(timeout=5)
