"""Receive bounded case-file uploads and publish isolated planning results."""
from base64 import b64decode
from binascii import Error as Base64Error
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from hashlib import sha256
import logging
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
from tempfile import TemporaryDirectory, mkdtemp
from threading import Lock
from time import monotonic
from zipfile import BadZipFile, ZipFile

from bridge import live as portal
from src.docs.pipeline import EXTENSIONS
from src.ingest.readers import SOURCES
from src.ingest.store import FILE_KINDS, key


MAX_UPLOAD = 64 * 1024**2
MAX_EXPANDED = 128 * 1024**2
MAX_CHUNK = 1024**2
MAX_BODY = 1_400_000
MAX_FILES = 512
MAX_SESSIONS = 8
SESSION_TTL = 3600
TOKEN = re.compile(r"[A-Za-z0-9_-]{22,64}")
ROOTS = {"soony", "suppliers"}
FILE_TYPES = EXTENSIONS | {".csv", ".tsv", ".json"}


class UploadError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def safe_parts(name):
    if not isinstance(name, str) or not 0 < len(name) <= 320 or re.search(r"[\\:\x00-\x1f\x7f]", name):
        raise UploadError("Invalid source file path.")
    parts = name.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise UploadError("Invalid source file path.")
    return parts


def case_path(name, seed, existing):
    parts = safe_parts(name)
    for index, part in enumerate(parts[:-1]):
        if part in ROOTS:
            path = PurePosixPath(*parts[index:])
            break
    else:
        filename = parts[-1]
        matches = existing.get(filename.casefold(), [])
        if len(matches) > 1:
            raise UploadError(f"{filename} has several case locations. Upload it in a ZIP with its case folder.")
        if matches:
            path = matches[0]
        else:
            candidates = {
                PurePosixPath(dataset.pattern).parent / filename
                for dataset in SOURCES if "*" not in str(PurePosixPath(dataset.pattern).parent)
                and dataset.matches(PurePosixPath(dataset.pattern).parent / filename)
            }
            if len(candidates) == 1:
                path = candidates.pop()
            elif PurePosixPath(filename).suffix.lower() == ".eml":
                path = PurePosixPath("soony/context", filename)
            elif re.match(r"(?:DN|SN|WZ)-", filename, re.I):
                path = PurePosixPath("soony/receiving/DC-HAM", filename)
            elif PurePosixPath(filename).suffix.lower() in EXTENSIONS and PurePosixPath(filename).suffix.lower() not in {".xlsx", ".txt", ".md"}:
                path = PurePosixPath("soony/context", filename)
            else:
                raise UploadError(f"Unrecognized case file {filename}. Use its existing case filename or a ZIP with its case folder.")
    if path.suffix.lower() not in FILE_TYPES or any(p.startswith((".", "~$")) for p in path.parts):
        raise UploadError(f"Unsupported case file {path.name}.")
    if path.suffix.lower() in {".csv", ".tsv", ".json"} and not (
        (seed / path).is_file() or any(dataset.matches(path) for dataset in SOURCES)
        or any(key(path.stem).startswith(prefix) for prefix in FILE_KINDS)
    ):
        raise UploadError(f"No case reader matches {path.as_posix()}.")
    return path


def stage_upload(payload, name, seed, staging, repeats=None):
    existing = {}
    for source in seed.rglob("*"):
        if source.is_file():
            existing.setdefault(source.name.casefold(), []).append(PurePosixPath(source.relative_to(seed).as_posix()))
    files = {}
    seen = {}

    def destination(member):
        relative = case_path(member, seed, existing).as_posix()
        previous = seen.setdefault(relative.casefold(), relative)
        dest = staging / previous
        dest.parent.mkdir(parents=True, exist_ok=True)
        files[previous] = dest
        return dest

    if Path(name).suffix.lower() != ".zip":
        shutil.copyfile(payload, destination(name))
        return files
    try:
        with ZipFile(payload) as archive:
            members = archive.infolist()
            if len(members) > MAX_FILES or sum(item.file_size for item in members) > MAX_EXPANDED:
                raise UploadError("ZIP exceeds 512 entries or 128 MB after extraction.", 413)
            for item in members:
                name = item.orig_filename
                parts = safe_parts(name.rstrip("/") if item.is_dir() else name)
                mode = stat.S_IFMT(item.external_attr >> 16)
                if mode not in {0, stat.S_IFREG, stat.S_IFDIR} or item.flag_bits & 1:
                    raise UploadError("ZIP contains a link, special file, or encrypted entry.")
                if item.is_dir() or "__MACOSX" in parts or parts[-1] in {".DS_Store", "Thumbs.db"}:
                    continue
                if not item.file_size:
                    raise UploadError(f"Empty ZIP entry {parts[-1]}.")
                dest = destination(item.filename)
                with archive.open(item) as source:
                    if dest.exists():
                        if digest_stream(source) != digest_file(dest):
                            raise UploadError(f"ZIP contains conflicting versions of {dest.name}.")
                        if repeats is not None:
                            repeats.append(dest.relative_to(staging).as_posix())
                    else:
                        with dest.open("xb") as out:
                            shutil.copyfileobj(source, out)
    except (BadZipFile, NotImplementedError, RuntimeError, OSError) as exc:
        raise UploadError("The ZIP could not be read.") from exc
    if not files:
        raise UploadError("ZIP contains no case files.")
    return files


def digest_stream(stream):
    digest = sha256()
    for block in iter(lambda: stream.read(256 * 1024), b""):
        digest.update(block)
    return digest.hexdigest()


def digest_file(path):
    with path.open("rb") as source:
        return digest_stream(source)


def changed_sources(seed, incoming):
    """Keep revised files and one copy of new content across both sources."""
    current = {p.relative_to(seed).as_posix(): digest_file(p)
               for p in seed.rglob("*") if p.is_file()}
    # Only content that survives the import can stand in for a renamed copy.
    seen = {digest for name, digest in current.items() if incoming.get(name, digest) == digest}
    changed = []
    for name in sorted(incoming, key=lambda name: (name not in current, name)):
        digest = incoming[name]
        if name in current:
            if current[name] == digest:
                continue
        elif digest in seen:
            continue
        seen.add(digest)
        changed.append(name)
    return changed


@dataclass
class Session:
    directory: TemporaryDirectory
    touched: float = field(default_factory=monotonic)
    status: str = "idle"
    upload_id: str = ""
    name: str = ""
    size: int = 0
    received: int = 0
    result: dict | None = None
    report: dict | None = None
    workspace: Path | None = None
    error: str | None = None

    @property
    def payload(self):
        return Path(self.directory.name) / "payload"

    def response(self, include_result=False):
        return {
            "status": self.status, "id": self.upload_id, "received": self.received,
            "name": self.name, "error": self.error,
            **({"result": self.result, "report": self.report} if include_result else {}),
        }


class Uploads:
    def __init__(self, seed, evaluate, portal_token=lambda: None):
        self.seed = seed
        self.evaluate = evaluate
        self.portal_token = portal_token
        self.sessions = {}
        self.lock = Lock()
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="upload")

    def cleanup(self):
        for token, entry in list(self.sessions.items()):
            if entry.status != "processing" and monotonic() - entry.touched > SESSION_TTL:
                self.remove(token)

    def remove(self, token):
        session = self.sessions.pop(token, None)
        if session:
            session.directory.cleanup()

    def request(self, token, body=None):
        if not TOKEN.fullmatch(token or ""):
            raise UploadError("Upload session required.", 403)
        with self.lock:
            self.cleanup()
            entry = self.sessions.get(token)
            if body is None:
                if entry:
                    entry.touched = monotonic()
                state = entry.response(True) if entry else {"status": "idle"}
                return {**state, "portal": {"configured": bool(self.portal_token()),
                                            "endpoint": portal.BASE + "/api/v1/files"}}
            if body == {"reset": True}:
                if entry and entry.status == "processing":
                    raise UploadError("Wait for the current upload to finish.", 409)
                self.remove(token)
                return {"status": "idle"}
            api_import = body.get("source") == "portal"
            if api_import:
                upload_id = body.get("id")
                if not isinstance(upload_id, str) or not TOKEN.fullmatch(upload_id):
                    raise UploadError("Invalid import identifier.")
                if not self.portal_token():
                    raise UploadError("The challenge API credential is unavailable on the server.", 503)
                name, size, offset = "Challenge API", 0, 0
            else:
                upload_id, name, size, offset, chunk = self.chunk(body)
            if entry and entry.upload_id == upload_id and (entry.name, entry.size) != (name, size):
                raise UploadError("Upload metadata changed. Select the file again.", 409)
            if not entry or entry.upload_id != upload_id:
                if offset or (entry and entry.status == "processing"):
                    raise UploadError("Finish the current upload or start again.", 409)
                if not entry:
                    if len(self.sessions) >= MAX_SESSIONS:
                        raise UploadError("Upload service is busy. Try again later.", 503)
                    entry = self.sessions[token] = Session(TemporaryDirectory(prefix="soony-upload-"))
                entry.payload.unlink(missing_ok=True)
                entry.upload_id, entry.name, entry.size = upload_id, name, size
                entry.received, entry.status, entry.error = 0, "uploading", None
                if api_import:
                    entry.status = "processing"
                    self.worker.submit(self.process, entry, True)
            entry.touched = monotonic()
            if api_import:
                return entry.response()
            if offset < entry.received and offset + len(chunk) <= entry.received:
                return entry.response()
            if offset != entry.received or entry.status != "uploading":
                raise UploadError("Upload chunks are out of order. Select the file again.", 409)
            with entry.payload.open("ab") as out:
                out.write(chunk)
            entry.received += len(chunk)
            if entry.received == size:
                entry.status = "processing"
                self.worker.submit(self.process, entry)
            return entry.response()

    @staticmethod
    def chunk(body):
        upload_id, name = body.get("id"), body.get("name")
        size, offset, encoded = body.get("size"), body.get("offset"), body.get("chunk")
        if not isinstance(upload_id, str) or not TOKEN.fullmatch(upload_id):
            raise UploadError("Invalid upload identifier.")
        if len(safe_parts(name)) != 1 or Path(name).suffix.lower() not in FILE_TYPES | {".zip"}:
            raise UploadError("Choose a supported case file or ZIP.")
        if type(size) is not int or not 0 < size <= MAX_UPLOAD:
            raise UploadError("Upload must be between 1 byte and 64 MB.", 413)
        if type(offset) is not int or offset < 0 or not isinstance(encoded, str):
            raise UploadError("Invalid upload chunk.")
        try:
            chunk = b64decode(encoded, validate=True)
        except (Base64Error, ValueError) as exc:
            raise UploadError("Invalid upload chunk.") from exc
        if not 0 < len(chunk) <= MAX_CHUNK or offset + len(chunk) > size:
            raise UploadError("Invalid upload chunk size.")
        return upload_id, name, size, offset, chunk

    def process(self, entry, api_import=False):
        parent = Path(entry.directory.name)
        candidate = None
        try:
            seed = entry.workspace / "data" if entry.workspace else self.seed()
            repeats = []
            with TemporaryDirectory(dir=parent) as stage:
                staging = Path(stage)
                if api_import:
                    token = self.portal_token()
                    manifest = portal.inventory(portal.fetch("/api/v1/files", token, limit=MAX_BODY))
                    if len(manifest) > MAX_FILES or sum(size for _, size in manifest.values()) > MAX_EXPANDED:
                        raise UploadError("Portal inventory exceeds the import limits.", 413)
                    incoming = {name: digest for name, (digest, _) in manifest.items()}
                    changed = changed_sources(seed, incoming)
                    files = {}
                    for name in changed:
                        path = staging / case_path(name, seed, {})
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(portal.download_file(name, token, *manifest[name]))
                        files[name] = path
                else:
                    staged = stage_upload(entry.payload, entry.name, seed, staging, repeats)
                    incoming = {name: digest_file(path) for name, path in staged.items()}
                    changed = changed_sources(seed, incoming)
                    files = {name: staged[name] for name in changed}

                rows = [{"name": name, "status": "ingested" if name in files else "unchanged"}
                        for name in sorted(incoming)]
                rows.extend({"name": name, "status": "unchanged"} for name in repeats)
                report = {"name": entry.name, "files": rows}
                if files:
                    candidate = Path(mkdtemp(dir=parent, prefix="scenario-"))
                    result = self.evaluate(seed, candidate, files)
                    result.update(id=entry.upload_id, files=rows)
        except Exception as exc:
            if isinstance(exc, (UploadError, portal.PortalError)):
                error = str(exc)
            else:
                logging.getLogger(__name__).warning("Import evaluation failed (%s)", type(exc).__name__)
                error = "The workflow could not process this import."
            with self.lock:
                if candidate:
                    shutil.rmtree(candidate, ignore_errors=True)
                entry.status, entry.error = "rejected", error
                self.finish(entry)
        else:
            with self.lock:
                if candidate:
                    previous = entry.workspace
                    entry.workspace, entry.result = candidate, result
                    if previous:
                        shutil.rmtree(previous, ignore_errors=True)
                entry.report, entry.status = report, "ready"
                self.finish(entry)

    @staticmethod
    def finish(entry):
        entry.payload.unlink(missing_ok=True)
        entry.touched = monotonic()
