"""Read PDF pages, render scanned pages, and capture local OCR evidence."""

import csv
import io
import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

from .schema import ITEM_CODE, quantity

import re


def command(args, timeout=45):
    process = subprocess.run(args, capture_output=True, timeout=timeout)
    if process.returncode:
        raise RuntimeError(f"{Path(args[0]).name} failed (exit {process.returncode})")
    return process.stdout.decode("utf-8", errors="replace")


def pdf_text(path, work):
    if shutil.which("gs"):
        command(["gs", "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-sDEVICE=txtwrite",
                 f"-sOutputFile={work / 'text-%05d.txt'}", str(path)])
        return [page.read_text(encoding="utf-8", errors="replace") for page in sorted(work.glob("text-*.txt"))]
    from pypdf import PdfReader

    return [page.extract_text(extraction_mode="layout") or "" for page in PdfReader(path).pages]


def render_page(path, page, work):
    output = work / f"image-{page:05d}.png"
    if shutil.which("gs"):
        command(["gs", "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pnggray", "-r200",
                 f"-dFirstPage={page}", f"-dLastPage={page}", f"-sOutputFile={output}", str(path)])
        return output
    import pypdfium2

    with pypdfium2.PdfDocument(path) as pdf:
        pdf[page - 1].render(scale=2.8).to_pil().save(output)
    return output


class LocalOCR:
    def __init__(self, repo, work):
        self.tesseract = shutil.which("tesseract")
        self.tessflags = []
        self.apple = repo / "runtime" / "soony-ocr"
        self.work = work
        self.apple_failed = False
        tessdata = repo / "runtime" / "tessdata"
        if self.tesseract:
            if (tessdata / "eng.traineddata").is_file():
                self.tessflags = ["--tessdata-dir", str(tessdata)]
            try:
                supported = set(command([self.tesseract, *self.tessflags, "--list-langs"]).splitlines()[1:])
                preferred = "+".join(lang for lang in ("eng", "pol", "kor", "chi_sim", "deu") if lang in supported)
                if preferred:
                    self.tessflags += ["-l", preferred]
            except (RuntimeError, subprocess.SubprocessError):
                self.tessflags = []

    def apple_text(self, path):
        if sys.platform != "darwin" or self.apple_failed:
            return ""
        try:
            if not self.apple.is_file():
                swiftc = shutil.which("swiftc")
                if not swiftc:
                    return ""
                self.apple = self.work / "soony-ocr"
                command([swiftc, "-module-cache-path", str(self.work / "swift-cache"),
                         str(Path(__file__).with_name("ocr.swift")), "-o", str(self.apple)])
            return command([str(self.apple), str(path)]).strip()
        except (OSError, RuntimeError, subprocess.SubprocessError):
            self.apple_failed = True
            return ""

    def read(self, path, *, receiving=False):
        if self.tesseract:
            args = [self.tesseract, str(path), "stdout", *self.tessflags, "--psm", "6"]
            try:
                if receiving:
                    table = csv.DictReader(io.StringIO(command([*args, "tsv"])), delimiter="\t",
                                           quoting=csv.QUOTE_NONE)
                    lines = {}
                    for word in table:
                        if word["level"] == "5" and word["text"]:
                            identity = tuple(word[key] for key in ("block_num", "par_num", "line_num"))
                            lines.setdefault(identity, []).append(word)
                    text = "\n".join(" ".join(word["text"] for word in line) for line in lines.values())
                    if text.strip():
                        return text, lines.values()
                else:
                    text = command(args)
                    if text.strip():
                        return text, ()
            except (OSError, RuntimeError, subprocess.SubprocessError):
                pass
        text = self.apple_text(path)
        if text:
            return text, ()
        raise RuntimeError("No readable image text from Tesseract or macOS Vision")

    def handwritten_quantities(self, path, lines, missing_materials):
        """Read digits below a quantity cell whose primary reading was illegible."""
        if not self.tesseract or not missing_materials:
            return {}
        try:
            from PIL import Image, ImageOps
        except ImportError:
            return {}

        readings = {}
        with Image.open(path) as image:
            for line in lines:
                code = next((word for word in line if re.fullmatch(ITEM_CODE, word["text"].strip("|"))
                             and word["text"].strip("|") in missing_materials), None)
                unit = next((word for word in line if word["text"].strip("|").lower()
                             in {"pcs", "szt", "ea", "stk"}), None)
                if not code or not unit:
                    continue
                top, height, right = int(code["top"]), int(code["height"]), int(unit["left"])
                box = (max(0, right - round(image.width * .16)), top + 2.5 * height,
                       right - round(image.width * .008), top + 5.5 * height)
                if box[2] <= box[0] or box[3] > image.height:
                    continue
                patch = ImageOps.autocontrast(ImageOps.grayscale(image.crop(tuple(map(int, box)))))
                votes = Counter()
                quotes = {}
                crop = self.work / "digits.png"
                for cutoff in (155, 180, 195):
                    bitmap = patch.point(lambda pixel: 0 if pixel < cutoff else 255)
                    ImageOps.expand(bitmap, border=18, fill=255).save(crop)
                    try:
                        raw = command([self.tesseract, str(crop), "stdout", "--psm", "7",
                                       "-c", "tessedit_char_whitelist=0123456789 "], timeout=15).strip()
                    except (OSError, RuntimeError, subprocess.SubprocessError):
                        continue
                    value = quantity(raw)
                    if value is not None and re.fullmatch(r"[1-9]\d{2,6}", str(value)):
                        votes[value] += 1
                        quotes[value] = raw
                if votes:
                    value, count = votes.most_common(1)[0]
                    if count >= 2:
                        readings[code["text"].strip("|")] = (value, quotes[value])
        return readings


def provider_cache_key(client):
    if client is None:
        return "none"
    return str(client.cache_key)


def checked_vision(client, path, kind):
    result = client.extract(path, kind=kind)
    if (not isinstance(result, dict) or not isinstance(result.get("facts", {}), dict)
            or not isinstance(result.get("text", ""), str)):
        raise ValueError("Invalid vision response")
    if not result.get("facts") and not result.get("text", "").strip():
        raise ValueError("Empty vision response")
    # Reject values such as NaN before writing either cache or JSONL.
    json.dumps(result, allow_nan=False)
    return result
