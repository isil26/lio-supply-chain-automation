"""Generate one SOONY_USERS_JSON entry using a password entered at the terminal."""
import argparse
import getpass
import hashlib
import json
import secrets
import sys
import unicodedata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username", help="account name used in the dashboard and audit records")
    args = parser.parse_args()
    name = args.username
    if not (1 <= len(name) <= 80 and name == name.strip() and name[0].isalnum()
            and all(c.isalnum() or unicodedata.category(c).startswith("M") or c in " .@_'-" for c in name)):
        parser.error("Use a 1–80 character account name starting with a letter or number.")
    if not sys.stdin.isatty():
        parser.error("Run this command in an interactive terminal.")
    password = getpass.getpass("New password: ")
    if not 12 <= len(password) <= 128 or password != getpass.getpass("Confirm password: "):
        parser.error("Enter the same 12–128 character password twice.")
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=3,
                         dklen=32, maxmem=64 * 1024 * 1024)
    print(json.dumps({name: f"scrypt-v1:{salt.hex()}:{key.hex()}"}))


if __name__ == "__main__":
    main()
