import runpy
import time
import traceback
from pathlib import Path

try:
    runpy.run_path("/app/production_server.py", run_name="__main__")
except BaseException:
    error = traceback.format_exc()
    print(error, flush=True)

    try:
        Path("/tmp/temli-test-startup-error.txt").write_text(
            error,
            encoding="utf-8",
        )
    except Exception:
        pass

    while True:
        time.sleep(3600)
