import zipfile
from datetime import datetime
from zoneinfo import ZoneInfo

from maai.jobs.backup import run_backup
from maai.jobs.scheduler import Scheduler


async def test_backup_contains_database_invoices_and_logs(app):
    await app.invoices.create_draft({
        "kind": "flat", "client_name": "TEST B", "client_email": "b@example.com", "project": "x",
        "services": [{"description": "Clean", "amount": 100}]}, task_id=None)
    name = run_backup(app)
    folder = app.config.data_dir / "local_drive" / "MAAI Agents" / "Backups"
    with zipfile.ZipFile(folder / name) as zf:
        names = zf.namelist()
    assert "maai.db" in names
    assert any(n.startswith("invoices/TEST-INV-") for n in names)
    assert any(n.startswith("logs/activity-") for n in names)


async def test_scheduler_runs_each_job_once_a_day(app, runner):
    async def invoice(call, prompt, ctx):
        return "ok"

    runner.on("invoice", invoice)
    tz = ZoneInfo(app.config.timezone)
    sched = Scheduler(app)
    assert await sched.tick(datetime(2026, 11, 12, 1, 0, tzinfo=tz)) == []
    assert await sched.tick(datetime(2026, 11, 12, 2, 1, tzinfo=tz)) == ["backup"]
    assert await sched.tick(datetime(2026, 11, 12, 9, 5, tzinfo=tz)) == ["reminders"]
    assert await sched.tick(datetime(2026, 11, 12, 23, 0, tzinfo=tz)) == []
    assert await sched.tick(datetime(2026, 11, 13, 9, 30, tzinfo=tz)) == ["backup", "reminders"]
