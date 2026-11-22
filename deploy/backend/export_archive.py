"""Write a scoped Git patch for verified supplier mail to the private repo runner."""
from pathlib import Path
import io
import re
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory

from sync_supplier_email_archive import ARCHIVE, scan_archive, write_archive

backend = Path("/var/lib/lio-live")
mirror = "/srv/lio/main.git"
sha = sys.stdin.readline().strip()
if not re.fullmatch("[0-9a-f]{40}", sha):
    raise SystemExit("Invalid release revision")
subprocess.run(["git", "--git-dir", mirror, "merge-base", "--is-ancestor", sha, "main"], check=True)
with TemporaryDirectory(dir=backend) as temp:
    checkout = Path(temp)
    snapshot = subprocess.check_output(["git", "--git-dir", mirror, "archive", sha,
                                        str(ARCHIVE), "deploy/vercel/team-password.txt"])
    with tarfile.open(fileobj=io.BytesIO(snapshot)) as files:
        files.extractall(checkout, filter="data")
    subprocess.run(["git", "init", "-q"], cwd=temp, check=True)
    subprocess.run(["git", "add", "--", str(ARCHIVE)], cwd=temp, check=True)
    subprocess.run(["git", "-c", "user.name=archive", "-c", "user.email=archive@localhost",
                    "commit", "-qm", "Archive baseline"], cwd=temp, check=True)
    archive, touched, added, captured = scan_archive(checkout, backend)
    if added:
        write_archive(checkout, archive, touched, captured)
        subprocess.run(["git", "add", "--", str(ARCHIVE)], cwd=temp, check=True)
        subprocess.run(["git", "diff", "--cached", "--check"], cwd=temp, check=True)
        subprocess.run(["git", "diff", "--cached", "--", str(ARCHIVE)], cwd=temp, check=True)
