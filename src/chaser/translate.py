"""Translate and cache supplier correspondence for offer previews and the shared mailbox."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import json
import hashlib
import re
import logging
import sqlite3
from contextlib import closing

from . import local_translation

SCHEMA = {"type": "object", "properties": {
    "language": {"type": "string"}, "english": {"type": "string"}, "summary": {"type": "string"}},
    "required": ["language", "english", "summary"]}
PROMPT = ("Translate this supplier email to plain English for a procurement manager. Keep every number, date, "
          "price, unit and reference exactly as written. Then give a one-sentence summary (max 25 words) of what the "
          "supplier offers or refuses: quantity, price, delivery time, conditions. Name the original language.\n\n"
          "EMAIL:\n{body}")
ENGLISH_WORDS = re.compile(r"\b(the|and|we|you|can|for|with|please|units|delivery|price|regards)\b", re.I)


def looks_english(text):
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return True
    non_ascii = sum(not c.isascii() for c in letters) / len(letters)
    return non_ascii < 0.02 and len(ENGLISH_WORDS.findall(text)) >= 3


def schema(con):
    con.execute("CREATE TABLE IF NOT EXISTS translations (hash TEXT PRIMARY KEY, language TEXT, english TEXT, summary TEXT)")


@lru_cache(maxsize=1)
def archived_previews():
    path = Path(__file__).resolve().parents[2] / "config" / "supplier_email_translations.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _cached(con, text, hint=None):
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if saved := archived_previews().get(key):
        return {"language": saved["language"], "english": saved["english"], "summary": None, "source": "translated"}
    if local_translation.language(text, hint) == "en" or (looks_english(text) and not local_translation.language(text)):
        return {"english": text, "summary": None, "language": "English", "source": "original"}
    row = con.execute("SELECT language, english, summary FROM translations WHERE hash=?", (key,)).fetchone()
    if row:
        return {"language": row[0], "english": row[1], "summary": row[2], "source": "translated"}
    return None


def translate(con, text, client=None, hint=None):
    schema(con)
    if not text:
        return {"english": None, "summary": None, "language": None, "source": "empty"}
    if previous := _cached(con, text, hint):
        return previous
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if client is None:
        try:
            local = local_translation.to_english(text, hint, looks_english)
        except (ImportError, RuntimeError, OSError, ValueError):
            logging.getLogger(__name__).exception("Local supplier translation failed")
            local = None
        if local and local["english"].strip():
            with con:
                con.execute("INSERT OR REPLACE INTO translations VALUES(?,?,?,?)",
                            (key, local["language"], local["english"], None))
            return local
    from src.llm.client import LLMCallError, LLMClient
    client = client or LLMClient()
    if not client.configured():
        return {"english": None, "summary": None, "language": None, "source": "unavailable",
                "error": "An English translation could not be prepared for this language."}
    try:
        result = client.complete_json("translate_supplier_email", SCHEMA, PROMPT.format(body=text[:6000]),
                                      source_text=text, validate_quotes=False)
    except (LLMCallError, OSError, ValueError) as exc:
        return {"english": None, "summary": None, "language": None, "source": "failed", "error": f"Translation failed ({exc})."}
    with con:
        con.execute("INSERT OR REPLACE INTO translations VALUES(?,?,?,?)",
                    (key, result["language"], result["english"], result["summary"]))
    return {**result, "source": "translated"}


def english(con, deal_id, client=None):
    row = con.execute("SELECT excerpt,language FROM deals WHERE id=?", (deal_id,)).fetchone()
    if row is None:
        raise KeyError(deal_id)
    original = row[0] or ""
    return {**translate(con, original, client, row[1]), "original": original}


def annotate(con, threads):
    """Only attach cached English to a dashboard read. Inference runs independently."""
    schema(con)
    for thread in threads:
        for msg in thread["messages"]:
            if text := msg.get("text"):
                cached = _cached(con, text, thread.get("language"))
                if cached and cached["source"] == "translated":
                    msg["english"] = cached["english"]


def run(stop, database, history_database=None):
    while not stop.is_set():
        try:
            with closing(sqlite3.connect(database, timeout=30)) as con:
                schema(con)
                seen = set()
                for path in dict.fromkeys((database, history_database)):
                    if not path or not Path(path).is_file():
                        continue
                    with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as source:
                        if not source.execute("SELECT 1 FROM sqlite_master WHERE name='messages'").fetchone():
                            continue
                        rows = source.execute("""SELECT m.body,c.language,m.time AS received FROM messages m JOIN chases c ON c.id=m.chase_id
                            UNION ALL SELECT body,language,'' FROM chases WHERE status LIKE '%draft' ORDER BY received DESC""").fetchall()
                    for body, lang, _ in rows:
                        if stop.is_set():
                            return
                        if not body or (body,lang) in seen:
                            continue
                        seen.add((body,lang))
                        if not _cached(con, body, lang):
                            translate(con, body, hint=lang)
        except (OSError, ValueError, sqlite3.Error):
            logging.getLogger(__name__).exception("Supplier translation worker will retry")
        stop.wait(15)
