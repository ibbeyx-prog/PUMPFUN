"""UTC stamps and atomic JSON writes for the paper book. No secrets."""
import json
import os
import shutil
import time
from datetime import datetime, timezone


def stamp():
    """UTC time, second resolution, for new ledger and report rows."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_stamp(text):
    """Unix seconds. New rows are UTC. Older rows are the process local clock."""
    text = str(text or "").strip()
    if not text:
        return None
    if "T" in text:
        try:
            return datetime.strptime(text.replace("Z", ""), "%Y-%m-%dT%H:%M:%S").replace(
                tzinfo=timezone.utc
            ).timestamp()
        except ValueError:
            return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return time.mktime(time.strptime(text, fmt))
        except ValueError:
            continue
    return None


def write_json(path, data, indent=2):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=indent)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def backup_book(data_dir):
    """One copy per UTC day of the book files. Config and keys are not copied."""
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dest = os.path.join(data_dir, "backups", day)
    marker = os.path.join(dest, ".ok")
    if os.path.exists(marker):
        return
    os.makedirs(dest, exist_ok=True)
    names = (
        "trades.csv", "state.json", "bank.json", "eye_knowledge.json",
        "agent_tune.json", "live_state.json", "reports.json", "wallets.json",
        "study.json", "chat.json",
    )
    for name in names:
        src = os.path.join(data_dir, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(dest, name))
    with open(marker, "w", encoding="utf-8") as handle:
        handle.write(stamp())
