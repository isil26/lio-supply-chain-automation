"""Probe observed failures offline. Run from repo root with PYTHONPATH=. python tests/drops/audit_drops.py."""

from contextlib import redirect_stderr
from email import policy
from email.message import EmailMessage
from io import StringIO
import json
from tempfile import TemporaryDirectory
from unittest.mock import patch

from openpyxl import Workbook
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from test_drops import Mirror, PART, PO, PO_HEADER, PRODUCT, SHIP, SHIP_HEADER, SHIPMENTS, STOCK, offline_environment

SUP = "suppliers/SUP-9001"


def pdf(path, *lines):
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject(key): NameObject(value) for key, value in {
        "/Type": "/Font", "/Subtype": "/Type1", "/BaseFont": "/Helvetica", "/Encoding": "/WinAnsiEncoding",
    }.items()})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    commands = ["BT /F1 12 Tf 16 TL 40 740 Td"]
    for line in lines:
        text = line.encode("cp1252").hex()
        commands.append(f"<{text}> Tj T*")
    stream = DecodedStreamObject()
    stream.set_data((" ".join(commands) + " ET").encode("ascii"))
    page[NameObject("/Contents")] = stream
    writer.write(path)
    writer.close()


def email(mirror, name, subject, body):
    message = EmailMessage(policy=policy.SMTP)
    message["From"] = "dispatch@example.invalid"
    message["To"] = "receiving@example.invalid"
    message["Subject"] = subject
    message.set_content(body)
    mirror.put(f"{SUP}/notices/{name}.eml", message.as_bytes())


def locale_csv(mirror, encoding):
    mirror.csv(PO, PO_HEADER + ("note",),
               [("4590000001", 1, "SUP-9001", PART, "100,0", "17.11.2026", "2,40", "open", "Änderung")],
               ";", encoding)


def ambiguous_eta(mirror):
    old = SHIPMENTS[0]
    # A US export intends October 11. The canonical CSV has no locale marker.
    mirror.csv(SHIP, SHIP_HEADER, [(*old[:5], "10/11/2026", "delayed", old[-1])])


def tracker_cancel(mirror):
    old = SHIPMENTS[0]
    mirror.csv(SHIP, SHIP_HEADER, [(*old[:6], "cancelled", old[-1])])
    book = Workbook()
    book.active.append(SHIP_HEADER)
    book.active.append(old)
    book.save(mirror.path("soony/logistics/open_shipments.xlsx"))
    book.close()


def split_same_id(mirror):
    old = SHIPMENTS[0]
    mirror.csv(SHIP, SHIP_HEADER, [
        (*old[:3], 20, *old[4:]),
        (old[0], "SEA-2", PART, 25, "sea", "2026-11-24", "delayed", old[-1]),
    ])


def scan(mirror, transform):
    im = Image.new("L", (1000, 520), color=255)
    draw = ImageDraw.Draw(im)
    for index, line in enumerate(("Delivery Note DN-261120-900", "Purchase Order: 4590000001",
                                  "Date: 11/20/2026", f"{PART}   40 PCS")):
        draw.text((40, 35 + 62 * index), line, fill=0, font=ImageFont.load_default(size=32))
    if transform == "rotate":
        im = im.rotate(90, expand=True)
    if transform == "degrade":
        im = im.resize((45, 23)).resize((360, 184))
    im.save(mirror.path("soony/receiving/DC-HAM/DN-261120-900.jpg"), quality=12 if transform == "degrade" else 85)


def run(label, mutate):
    with TemporaryDirectory(prefix="soony-audit-") as folder, offline_environment():
        mirror = Mirror(folder)
        baseline_ui, baseline, _, _ = mirror.refresh()
        mutate(mirror)
        crash = False
        # Run exactly one real background iteration, including its error publication.
        with patch.object(mirror.loop.trigger, "wait", side_effect=lambda _: mirror.loop.stop.set()):
            with redirect_stderr(StringIO()) as stderr:
                mirror.loop.background()
                crash = bool(stderr.getvalue())
        ui, truth, docs, orders = mirror.snapshot()
        print(json.dumps({
            "case": label, "cycle_exception": crash, "sync_error": ui["sync"]["error"],
            "sync_events": [event["action"] for event in ui["sync"].get("events", [])],
            "documents": [{"file": doc["source"], "fields": sorted(doc["fields"]),
                           "error": doc.get("error"), "warnings": doc.get("warnings")} for doc in docs],
            "activity_warnings": [event["tool"] for event in ui["activity"] if event["type"] == "warning"],
            "issues": [issue["kind"] for issue in truth["issues"] if issue["kind"]],
            "on_hand": truth["parts"][PART]["on_hand"], "gap": truth["parts"][PART]["shortfall"],
            "p50": truth["editions"][PRODUCT]["p50"], "forecast_changed": truth["editions"] != baseline["editions"],
            "options_changed": ui["options"] != baseline_ui["options"],
            "options": [option["kind"] for option in ui["options"]],
            "inbound": [[row["id"], row["eta"], row["quantity"]] for row in truth["inbound"]],
            "typed_price": orders[0]["unit_price"],
            "drop_files": [event["file"] for event in ui["drop"]["changes"]] if ui["drop"] != baseline_ui["drop"] else [],
        }, ensure_ascii=False))


def main():
    cases = {
        "German notice PDF": lambda m: pdf(m.path(f"{SUP}/notices/Verzoegerung.pdf"),
                                           "Lieferverzögerung", f"{PART}: 45 Stück verspätet.",
                                           "Sendung SEA-1: Neuer Liefertermin 24.11.2026."),
        "German EML": lambda m: email(m, "Verzoegerung", "Lieferverzögerung", "SEA-1 verspätet bis 24.11.2026."),
        "Japanese EML": lambda m: email(m, "supplier-delay-jp", "出荷遅延のお知らせ", "SEA-1 は11月24日まで遅延します。"),
        "confirmation control": lambda m: pdf(m.path(f"{SUP}/order_confirmations/OA99000001.pdf"),
                                               "Purchase Order: 4590000001", f"00010  {PART}  Sleeve  75  2.40  EUR  2026-11-24"),
        "reordered confirmation": lambda m: pdf(m.path(f"{SUP}/order_confirmations/ACK-9001.pdf"),
                                                 "Purchase Order: 4590000001",
                                                 "Ship date       Price       Quantity       Item          Line",
                                                 f"24.11.2026      EUR 2,40    75             {PART}   00010"),
        "UTF-16 PO": lambda m: locale_csv(m, "utf-16"),
        "Windows-1252 PO": lambda m: locale_csv(m, "cp1252"),
        "unknown PO header": lambda m: m.csv(PO, ("replacement_key", *PO_HEADER[1:]),
                                             [("4590000001", 1, "SUP-9001", PART, 100, "2026-11-17", 2, "open")]),
        "ambiguous US ETA": ambiguous_eta,
        "cancelled SAP vs active tracker": tracker_cancel,
        "split under one ID": split_same_id,
        "receipt control": lambda m: scan(m, "none"),
        "rotated receipt": lambda m: scan(m, "rotate"),
        "low-quality receipt": lambda m: scan(m, "degrade"),
        "corrupt PDF": lambda m: m.put(f"{SUP}/notices/recall.pdf", b"%PDF-1.7\ntruncated"),
        "empty ERP": lambda m: m.put(STOCK, b""),
        "header-only ERP": lambda m: m.csv(STOCK, ("snapshot_date", "site", "material_id", "batch", "quantity"), []),
        "corrupt workbook": lambda m: m.put("launch.xlsx", b"not a zip archive"),
        "copy at second path": lambda m: m.put("soony/erp/stock_snapshot_copy.csv", m.path(STOCK).read_bytes()),
        "changed copy at second path": lambda m: m.stock("2026-11-20", [("LOT-A", 10)], "soony/erp/stock_snapshot_copy.csv"),
    }
    for label, mutate in cases.items():
        run(label, mutate)


if __name__ == "__main__":
    main()
