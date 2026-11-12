"""One-time Google sign-in (Gmail drafts + Drive + Docs).

Works on a server with no screen:
  1. Run:  python scripts/google_login.py
  2. Open the link it prints on your computer or phone and sign in.
  3. Google then shows a page that won't load ("This site can't be reached").
     That's expected. Copy the FULL address from the browser's address bar
     and paste it back here.
The saved login (data/google_token.json) is private and never uploaded.
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: E402

from maai.config import load_config  # noqa: E402
from maai.integrations.workspace import SCOPES  # noqa: E402

REDIRECT = "http://localhost:8765/"


def main() -> int:
    config = load_config()
    secret_file = ROOT / config.secret("GOOGLE_CLIENT_SECRET_FILE", "data/google_client_secret.json")
    token_file = ROOT / config.secret("GOOGLE_TOKEN_FILE", "data/google_token.json")
    if not secret_file.exists():
        print(f"Missing {secret_file}. Download the OAuth client file from Google Cloud (docs/SETUP.md step 3).")
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(str(secret_file), SCOPES, redirect_uri=REDIRECT)
    url, _ = flow.authorization_url(access_type="offline", prompt="consent")
    print("\n1) Open this link and sign in with the Google account the agents should use:\n")
    print(url)
    print("\n2) After you allow access, the page won't load. That's OK.")
    pasted = input("3) Paste the full address from the address bar here and press Enter:\n> ").strip()
    code = parse_qs(urlparse(pasted).query).get("code", [pasted])[0]
    flow.fetch_token(code=code)

    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(flow.credentials.to_json(), encoding="utf-8")
    token_file.chmod(0o600)
    print(f"\n✅ Google connected. Login saved to {token_file.relative_to(ROOT)} (private, not uploaded).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
