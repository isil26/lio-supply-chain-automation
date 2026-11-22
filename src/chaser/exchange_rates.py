"""Refresh ECB euro reference rates off the request path and keep the last publication on disk."""
from contextlib import closing
from datetime import date, datetime, timezone
import json
import logging
import math
import sqlite3
from urllib.request import urlopen
from xml.etree import ElementTree

FEED = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
SOURCE = "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html"
NAMESPACE = "{http://www.ecb.int/vocabulary/2002-08-01/eurofxref}"


def parse(document, today):
    day = ElementTree.fromstring(document).find(f".//{NAMESPACE}Cube[@time]")
    if day is None or date.fromisoformat(day.attrib["time"]) > today:
        raise ValueError("Invalid ECB publication date")
    rates = {"EUR": 1.0}
    for item in day.findall(NAMESPACE + "Cube"):
        code, value = item.attrib["currency"], float(item.attrib["rate"])
        if len(code) != 3 or not code.isalpha() or not code.isupper() or code in rates or not math.isfinite(value) or value <= 0:
            raise ValueError("Invalid ECB currency rate")
        rates[code] = 1 / value  # The ECB publishes foreign units for one euro.
    if not {"USD", "CNY", "INR", "KRW", "PLN"} <= rates.keys():
        raise ValueError("Incomplete ECB publication")
    return day.attrib["time"], rates


def refresh(con, document, now):
    published, rates = parse(document, now.date())
    with con:
        con.execute("""CREATE TABLE IF NOT EXISTS ecb_reference (
            id INTEGER PRIMARY KEY CHECK(id=1), published TEXT NOT NULL, rates TEXT NOT NULL, checked TEXT NOT NULL)""")
        con.execute("""INSERT INTO ecb_reference VALUES(1,?,?,?) ON CONFLICT(id) DO UPDATE SET
            published=excluded.published,rates=excluded.rates,checked=excluded.checked WHERE excluded.published>=published""",
                    (published,json.dumps(rates),now.isoformat()))


def snapshot(con):
    if con.execute("SELECT 1 FROM sqlite_master WHERE name='ecb_reference'").fetchone():
        row = con.execute("SELECT published,rates,checked FROM ecb_reference WHERE id=1").fetchone()
        if row:
            return dict(source="ECB", url=SOURCE, asOf=row[0], checkedAt=row[2], eurPerUnit=json.loads(row[1]))
    from .negotiate import fx_rates
    return dict(source="Planning estimate", url=None, asOf=None, checkedAt=None, eurPerUnit=fx_rates())


def run(stop, database):
    while not stop.is_set():
        try:
            with urlopen(FEED, timeout=12) as response:
                document = response.read(65537)
            if len(document) > 65536:
                raise ValueError("Oversized ECB publication")
            with closing(sqlite3.connect(database,timeout=30)) as con:
                refresh(con,document,datetime.now(timezone.utc))
            wait = 3600
        except (OSError, ValueError, KeyError, ElementTree.ParseError, sqlite3.Error):
            logging.getLogger(__name__).exception("ECB refresh failed; retaining last published rates")
            wait = 300
        stop.wait(wait)
