"""JSON files in the data directory, written atomically.

On Railway the data directory is the attached volume, whose path Railway
provides by itself. Without a volume, every redeploy starts from nothing.
"""

import json
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
                or Path(__file__).parent / "data")


def load(name, default):
    path = DATA_DIR / f"{name}.json"
    if not path.exists():
        return default
    return json.loads(path.read_text())


def save(name, data, private=False):
    """Write to a temporary file and rename it over the old one, so a crash
    or redeploy mid-write never leaves a truncated file behind. `private`
    files (API keys) are readable by the bot's own user only."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{name}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    if private:
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)
