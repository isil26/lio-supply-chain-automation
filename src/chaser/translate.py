"""English version of a supplier's email for the offers table (gülşah-agent, Gülşah 22 Nov).

"Their words" showed the reply in Polish / Korean / Chinese. `english(con, deal_id)` returns
{english, summary, language, source}: the email in English plus a one-line gist. English emails
are returned as they are; others go through the shared LLM client (src/llm/client.py, cached on
disk and in the `translations` table, so each email is translated once). Without a configured
model it says so instead of guessing.
"""
from __future__ import annotations

import hashlib
import re

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


def translate(con, text, client=None):
    schema(con)
    if not text:
        return {"english": None, "summary": None, "language": None, "source": "empty"}
    if looks_english(text):
        return {"english": text, "summary": None, "language": "English", "source": "original"}
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()
    row = con.execute("SELECT language, english, summary FROM translations WHERE hash=?", (key,)).fetchone()
    if row:
        return {"language": row[0], "english": row[1], "summary": row[2], "source": "translated"}
    from src.llm.client import LLMCallError, LLMClient
    client = client or LLMClient()
    if not client.configured():
        return {"english": None, "summary": None, "language": None, "source": "unavailable",
                "error": "Translation needs the AI model, which is not switched on for this server."}
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
    row = con.execute("SELECT excerpt FROM deals WHERE id=?", (deal_id,)).fetchone()
    if row is None:
        raise KeyError(deal_id)
    return translate(con, row[0] or "", client)
