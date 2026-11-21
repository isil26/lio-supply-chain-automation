"""Load the team mailbox settings from deploy/mail/team-gmail.env.

Values already in the environment win. CHASER_REAL_SMTP is never set here,
so real sending stays off unless a person turns it on.
"""
import os
from pathlib import Path

TEAM_MAIL_ENV = Path(__file__).resolve().parents[2] / "deploy" / "mail" / "team-gmail.env"
_KEYS = {"CHASER_SENDER", "CHASER_SMTP_HOST", "CHASER_SMTP_PORT", "CHASER_SMTP_USERNAME", "CHASER_SMTP_PASSWORD",
         "SOONY_IMAP_HOST", "SOONY_IMAP_PORT", "SOONY_IMAP_USER", "SOONY_IMAP_PASSWORD"}


def load_team_mail_env(path=TEAM_MAIL_ENV):
    if os.getenv("CHASER_NO_TEAM_MAIL") == "1" or not Path(path).is_file():
        return False
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key in _KEYS and not line.lstrip().startswith("#"):
            os.environ.setdefault(key, value.strip())
    return True
