#!/usr/bin/env python3
"""Reject private mailbox settings in the Git index or in proposed Git history."""
import argparse
import hashlib
import re
import subprocess
import sys

PRIVATE_PATH = "deploy/mail/team-gmail.env"
EXPOSED_DIGEST = "1773c0704f0afeb4c12dd1bf2a86c9a988e8bb51b670cf21efe04f3d79e4c88b"
# Google app passwords are 16 letters, sometimes copied as four groups.
PASSWORD_FORM = rb"(?:[a-z]{16}|[a-z]{4}(?:[ \t]+[a-z]{4}){3})"
CANDIDATE = re.compile(rb"(?<![a-z])" + PASSWORD_FORM + rb"(?![a-z])")
MAIL_SETTING = re.compile(
    rb"""(?im)\b(?:CHASER_SMTP_PASSWORD|SOONY_IMAP_PASSWORD)["']?[ \t]*[:=][ \t]*["']?"""
    + PASSWORD_FORM + rb"""(?=["'\s,}\#]|$)"""
)


def git(*args, data=None):
    return subprocess.check_output(["git", *args], input=data)


def sensitive(content):
    if MAIL_SETTING.search(content):
        return True
    for match in CANDIDATE.finditer(content):
        password = b"".join(match[0].split())
        if hashlib.sha256(password).hexdigest() == EXPOSED_DIGEST:
            return True
    return False


def check_objects(objects):
    if not objects:
        return True
    query = b"".join(oid + b"\n" for oid in objects)
    info = git("cat-file", "--batch-check=%(objectname) %(objecttype)", data=query)
    with subprocess.Popen(["git", "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE) as proc:
        for row in info.splitlines():
            oid, kind = row.split()
            if kind not in (b"commit", b"blob", b"tag"):
                continue
            proc.stdin.write(oid + b"\n")
            proc.stdin.flush()
            size = int(proc.stdout.readline().split()[2])
            content = proc.stdout.read(size)
            proc.stdout.read(1)
            if sensitive(content):
                print("Blocked a Gmail credential in a Git object (" + oid[:12].decode() + ").", file=sys.stderr)
                proc.stdin.close()
                return False
        proc.stdin.close()
    return True


def staged():
    if git("ls-files", "--cached", "--", PRIVATE_PATH):
        return False
    raw = git("diff", "--cached", "--raw", "--no-renames", "--no-abbrev", "-z", "--diff-filter=AMT")
    fields = raw.split(b"\0")
    return check_objects({header.split()[3] for header in fields[:-1:2]})


def history(refs):
    # An old branch merged after a cleanup can reintroduce a secret in ancestry
    # even if its merge commit has a clean tree.
    if not refs:
        return True
    if git("rev-list", "-1", "--full-history", *refs, "--", PRIVATE_PATH).strip():
        return False
    objects = git("rev-list", "--objects", "--no-object-names", *refs).splitlines()
    return check_objects(set(objects))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--staged", action="store_true")
    modes.add_argument("--history", nargs="+", metavar="REV")
    modes.add_argument("--pre-push", action="store_true")
    args = parser.parse_args()
    if args.staged:
        ok = staged()
    elif args.pre_push:
        refs = {line.split()[1] for line in sys.stdin if line.strip()}
        ok = history([oid for oid in refs if oid.strip("0")])
    else:
        ok = history(args.history)
    if not ok:
        sys.exit("Remove the private mailbox file or credential from the proposed commits before continuing.")


if __name__ == "__main__":
    main()
