"""Nightly backup.

Packs the database (tasks, invoices, clients, approvals, costs), the
invoice files and the logs into one .zip and uploads it to Google Drive
("MAAI Agents/Backups"). Before Google is connected, it goes to data/backups/.
Backups older than `backup_keep_days` are moved to Drive's trash, which
Google keeps for 30 more days, so nothing is lost for good by mistake.
"""

from __future__ import annotations

import logging
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..app import App

log = logging.getLogger(__name__)


def make_backup_zip(app: "App", dest_dir: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    dest_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dest_dir / f"maai-backup-{stamp}.zip"
    with tempfile.TemporaryDirectory() as tmp:
        db_copy = Path(tmp) / "maai.db"
        app.db.backup_to(db_copy)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(db_copy, "maai.db")
            for folder, prefix in ((app.config.data_dir / "invoices", "invoices"), (app.config.logs_dir, "logs")):
                if folder.exists():
                    for file in sorted(folder.rglob("*")):
                        if file.is_file():
                            zf.write(file, f"{prefix}/{file.relative_to(folder)}")
    zip_path.chmod(0o600)
    return zip_path


def _created(entry: dict) -> datetime:
    value = entry.get("createdTime")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def run_backup(app: "App") -> str:
    keep_days = int(app.config.section("schedule").get("backup_keep_days", 30))
    local_dir = app.config.data_dir / "backups"
    zip_path = make_backup_zip(app, local_dir)
    ws = app.workspace
    folder = ws.ensure_folder("Backups")
    ws.upload_file(zip_path, zip_path.name, folder, "application/zip")
    if not ws.is_local:
        zip_path.unlink()  # the copy lives in Drive now

    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    removed = 0
    for entry in ws.list_files(folder):
        if entry["name"].startswith("maai-backup-") and _created(entry) < cutoff:
            ws.trash_file(entry["id"])
            removed += 1
    app.activity.record("system", "backup_done", ref=zip_path.name, note=f"old backups trashed: {removed}")
    return zip_path.name
