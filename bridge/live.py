"""Verified, private portal snapshots for the Mac planning worker."""

from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .sync import BASE


class PortalError(ValueError):
    """A safe error description for the authenticated dashboard."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        # Never send the team bearer token to a different origin.
        return None


def fetch(path, token):
    req = Request(BASE + path, headers={"Authorization": f"Bearer {token}"})
    try:
        with build_opener(NoRedirect()).open(req, timeout=15) as response:
            return response.read()
    except HTTPError as error:
        raise PortalError(f"Portal API returned HTTP {error.code}.") from None
    except (OSError, URLError):
        raise PortalError("Portal API is temporarily unreachable.") from None


def inventory(body):
    try:
        rows = json.loads(body)["files"]
        if not isinstance(rows, list) or not rows:
            raise ValueError
        files, seen = {}, set()
        for row in rows:
            name, digest, size = row["path"], row["sha256"], row["bytes"]
            path = PurePosixPath(name)
            if (len(path.parts) < 2 or path.parts[0] not in {"soony", "suppliers"}
                    or name != path.as_posix() or any(part.startswith(".") for part in path.parts)
                    or "\\" in name or any(ord(char) < 32 for char in name) or name.casefold() in seen
                    or not re.fullmatch(r"[0-9a-fA-F]{64}", digest)
                    or type(size) is not int or size < 0):
                raise ValueError
            seen.add(name.casefold())
            files[name] = (digest.lower(), size)
        if not any(name.startswith("soony/context/") for name in files):
            raise ValueError
    except (TypeError, ValueError, KeyError):
        raise PortalError("Portal file inventory is invalid.") from None
    return files


def _verified(path, digest, size):
    if not path.is_file() or path.stat().st_size != size:
        return False
    with path.open("rb") as stream:
        return sha256(stream.read()).hexdigest() == digest


class PortalMirror:
    """Keep an immutable raw snapshot per manifest and an atomic accepted pointer."""

    def __init__(self, workspace, seed):
        self.workspace = Path(workspace)
        self.seed = Path(seed)
        self.snapshots = self.workspace / "snapshots"
        self.marker = self.workspace / "current"
        self.token_file = self.workspace / ".soony_token"

    @staticmethod
    def manifest(data):
        return data.parent / "bridge" / "state.json"

    def current(self):
        if not self.marker.is_file():
            return None
        snapshot = self.marker.read_text().strip()
        if not re.fullmatch(r"[a-f0-9]{64}", snapshot):
            raise PortalError("Local portal snapshot pointer is invalid.")
        data = self.snapshots / snapshot / "data"
        if not data.is_dir() or not self.manifest(data).is_file():
            raise PortalError("Last verified portal snapshot is unavailable.")
        return data

    def refresh(self):
        token = self.token_file.read_text().strip() if self.token_file.is_file() else ""
        if not token:
            raise PortalError("Portal credentials are unavailable on this Mac.")
        files = inventory(fetch("/api/v1/files", token))
        manifest = json.dumps({p: digest for p, (digest, _) in files.items()},
                              sort_keys=True, separators=(",", ":"))
        snapshot = self.snapshots / sha256(manifest.encode()).hexdigest()
        if (snapshot / "data").is_dir():
            return snapshot / "data"
        previous = self.current()
        self.snapshots.mkdir(mode=0o700, parents=True, exist_ok=True)
        with TemporaryDirectory(dir=self.snapshots, prefix=".download-") as temp:
            staging = Path(temp) / "snapshot"
            data = staging / "data"
            for name, (digest, size) in files.items():
                target = data / name
                target.parent.mkdir(parents=True, exist_ok=True)
                for existing in (previous, self.seed):
                    if existing and _verified(existing / name, digest, size):
                        shutil.copyfile(existing / name, target)
                        break
                else:
                    body = fetch("/api/v1/files/" + quote(name), token)
                    if len(body) != size or sha256(body).hexdigest() != digest:
                        raise PortalError("A portal file changed during download or failed its hash check.")
                    target.write_bytes(body)
            state = self.manifest(data)
            state.parent.mkdir()
            state.write_text(manifest, encoding="utf-8")
            try:
                staging.rename(snapshot)
            except FileExistsError:
                # A second worker may have finished this same manifest first.
                if not (snapshot / "data").is_dir():
                    raise
        return snapshot / "data"

    def accept(self, data):
        with TemporaryDirectory(dir=self.workspace, prefix=".accepted-") as temp:
            pointer = Path(temp) / "current"
            pointer.write_text(data.parent.name + "\n")
            os.replace(pointer, self.marker)
