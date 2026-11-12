"""Google Workspace connection (Gmail drafts, Drive files, Google Docs).

Two versions with the same functions:
  GoogleWorkspace  real Gmail/Drive/Docs, after you run scripts/google_login.py
  LocalWorkspace   practice version with no Google: files go to data/local_drive/,
                   emails are saved as .eml files in data/outbox/

Permissions requested from Google (the smallest that do the job):
  gmail.compose  create drafts and send them (it cannot read your inbox)
  drive          copy the invoice template, save PDFs and backups
  documents      fill in the invoice copy
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import shutil
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
]

FOLDER_MIME = "application/vnd.google-apps.folder"
ROOT_FOLDER = "MAAI Agents"


class Workspace(Protocol):
    is_local: bool
    supports_docs: bool

    def ensure_folder(self, *path: str) -> str: ...
    def copy_file(self, file_id: str, name: str, parent_id: str) -> str: ...
    def get_doc(self, doc_id: str) -> dict[str, Any]: ...
    def update_doc(self, doc_id: str, requests: list[dict[str, Any]]) -> None: ...
    def export_pdf(self, file_id: str) -> bytes: ...
    def upload_file(self, local_path: Path, name: str, parent_id: str, mime: str | None = None) -> str: ...
    def list_files(self, parent_id: str) -> list[dict[str, Any]]: ...
    def trash_file(self, file_id: str) -> None: ...
    def create_email_draft(self, to: str, subject: str, body: str, attachments: list[Path]) -> str: ...
    def send_email_draft(self, draft_id: str) -> str: ...
    def file_link(self, file_id: str) -> str: ...


def build_email(to: str, subject: str, body: str, attachments: list[Path]) -> EmailMessage:
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    for path in attachments:
        path = Path(path)
        mime, _ = mimetypes.guess_type(path.name)
        maintype, subtype = (mime or "application/octet-stream").split("/", 1)
        msg.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name)
    return msg


# --------------------------------------------------------------------------
# Real Google
# --------------------------------------------------------------------------
class GoogleWorkspace:
    is_local = False
    supports_docs = True

    def __init__(self, token_file: Path):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
        if not creds.valid and creds.refresh_token:
            creds.refresh(Request())
            token_file.write_text(creds.to_json(), encoding="utf-8")
            token_file.chmod(0o600)
        self._drive = build("drive", "v3", credentials=creds, cache_discovery=False)
        self._docs = build("docs", "v1", credentials=creds, cache_discovery=False)
        self._gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)
        self._folder_cache: dict[tuple[str, ...], str] = {}

    # Drive ------------------------------------------------------------------
    def _find_or_create(self, name: str, parent: str | None) -> str:
        safe = name.replace("\\", "\\\\").replace("'", "\\'")
        q = f"name = '{safe}' and mimeType = '{FOLDER_MIME}' and trashed = false"
        q += f" and '{parent}' in parents" if parent else " and 'root' in parents"
        found = self._drive.files().list(q=q, fields="files(id)", pageSize=1).execute().get("files", [])
        if found:
            return found[0]["id"]
        body: dict[str, Any] = {"name": name, "mimeType": FOLDER_MIME}
        if parent:
            body["parents"] = [parent]
        return self._drive.files().create(body=body, fields="id").execute()["id"]

    def ensure_folder(self, *path: str) -> str:
        full = (ROOT_FOLDER, *path)
        if full in self._folder_cache:
            return self._folder_cache[full]
        parent: str | None = None
        for name in full:
            parent = self._find_or_create(name, parent)
        self._folder_cache[full] = parent
        return parent

    def copy_file(self, file_id: str, name: str, parent_id: str) -> str:
        body = {"name": name, "parents": [parent_id]}
        return self._drive.files().copy(fileId=file_id, body=body, fields="id", supportsAllDrives=True).execute()["id"]

    def export_pdf(self, file_id: str) -> bytes:
        return self._drive.files().export(fileId=file_id, mimeType="application/pdf").execute()

    def upload_file(self, local_path: Path, name: str, parent_id: str, mime: str | None = None) -> str:
        from googleapiclient.http import MediaFileUpload

        mime = mime or mimetypes.guess_type(name)[0] or "application/octet-stream"
        media = MediaFileUpload(str(local_path), mimetype=mime, resumable=False)
        body = {"name": name, "parents": [parent_id]}
        return self._drive.files().create(body=body, media_body=media, fields="id").execute()["id"]

    def list_files(self, parent_id: str) -> list[dict[str, Any]]:
        q = f"'{parent_id}' in parents and trashed = false"
        resp = self._drive.files().list(q=q, fields="files(id,name,createdTime)", orderBy="createdTime",
                                        pageSize=200).execute()
        return resp.get("files", [])

    def trash_file(self, file_id: str) -> None:
        # Trash (not permanent delete): Google keeps it 30 days, so it can be restored.
        self._drive.files().update(fileId=file_id, body={"trashed": True}).execute()

    def file_link(self, file_id: str) -> str:
        return f"https://drive.google.com/file/d/{file_id}/view"

    # Docs -------------------------------------------------------------------
    def get_doc(self, doc_id: str) -> dict[str, Any]:
        return self._docs.documents().get(documentId=doc_id).execute()

    def update_doc(self, doc_id: str, requests: list[dict[str, Any]]) -> None:
        if requests:
            self._docs.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()

    # Gmail ------------------------------------------------------------------
    def create_email_draft(self, to: str, subject: str, body: str, attachments: list[Path]) -> str:
        raw = base64.urlsafe_b64encode(build_email(to, subject, body, attachments).as_bytes()).decode()
        draft = self._gmail.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
        return draft["id"]

    def send_email_draft(self, draft_id: str) -> str:
        sent = self._gmail.users().drafts().send(userId="me", body={"id": draft_id}).execute()
        return sent.get("id", "")


# --------------------------------------------------------------------------
# Practice version (no Google account needed)
# --------------------------------------------------------------------------
class LocalWorkspace:
    is_local = True
    supports_docs = False

    def __init__(self, data_dir: Path):
        self.drive_root = data_dir / "local_drive"
        self.outbox = data_dir / "outbox"
        for folder in (self.drive_root, self.outbox, self.outbox / "sent"):
            folder.mkdir(parents=True, exist_ok=True)

    def ensure_folder(self, *path: str) -> str:
        folder = self.drive_root.joinpath(ROOT_FOLDER, *path)
        folder.mkdir(parents=True, exist_ok=True)
        return str(folder)

    def copy_file(self, file_id: str, name: str, parent_id: str) -> str:
        raise NotImplementedError("Google Docs copies need the Google connection")

    def get_doc(self, doc_id: str) -> dict[str, Any]:
        raise NotImplementedError("Google Docs need the Google connection")

    def update_doc(self, doc_id: str, requests: list[dict[str, Any]]) -> None:
        raise NotImplementedError("Google Docs need the Google connection")

    def export_pdf(self, file_id: str) -> bytes:
        raise NotImplementedError("PDF export needs the Google connection")

    def upload_file(self, local_path: Path, name: str, parent_id: str, mime: str | None = None) -> str:
        dest = Path(parent_id) / name
        shutil.copyfile(local_path, dest)
        return str(dest)

    def list_files(self, parent_id: str) -> list[dict[str, Any]]:
        files = sorted(Path(parent_id).glob("*"), key=lambda p: p.stat().st_mtime)
        return [{"id": str(p), "name": p.name, "createdTime": p.stat().st_mtime} for p in files if p.is_file()]

    def trash_file(self, file_id: str) -> None:
        path = Path(file_id)
        trash = path.parent / ".trash"
        trash.mkdir(exist_ok=True)
        path.rename(trash / path.name)

    def file_link(self, file_id: str) -> str:
        return str(file_id)

    def create_email_draft(self, to: str, subject: str, body: str, attachments: list[Path]) -> str:
        existing = len(list(self.outbox.glob("draft-*.eml"))) + len(list((self.outbox / "sent").glob("*.eml")))
        draft_id = f"draft-{existing + 1:04d}"
        (self.outbox / f"{draft_id}.eml").write_bytes(build_email(to, subject, body, attachments).as_bytes())
        return draft_id

    def send_email_draft(self, draft_id: str) -> str:
        src = self.outbox / f"{draft_id}.eml"
        src.rename(self.outbox / "sent" / src.name)
        return f"local:{draft_id}"


def open_workspace(config) -> Workspace:
    """Use real Google if the login token exists, otherwise the practice version."""
    token = config.root / config.secret("GOOGLE_TOKEN_FILE", "data/google_token.json")
    if token.exists():
        try:
            return GoogleWorkspace(token)
        except Exception as exc:
            if not config.dry_run:
                # In live mode never pretend: a silent fallback would "send" to a local folder.
                raise RuntimeError("Google connection failed. Run scripts/google_login.py again.") from exc
            log.error("Google connection failed (%s). Using the practice workspace.", type(exc).__name__)
    elif not config.dry_run:
        raise RuntimeError("Live mode needs the Google connection. Run scripts/google_login.py first.")
    return LocalWorkspace(config.data_dir)


def client_secret_info(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
