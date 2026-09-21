import runpy
import traceback
from pathlib import Path

try:
    runpy.run_path("/app/production_server.py", run_name="__main__")
except BaseException:
    folder = Path("/app/data")
    folder.mkdir(parents=True, exist_ok=True)
    error_file = folder / "temli-test-startup-error.txt"
    error_file.write_text(traceback.format_exc(), encoding="utf-8")
    raise
