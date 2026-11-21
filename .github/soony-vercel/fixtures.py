"""Stage fictional hosted fixtures and verify the public build before upload."""
import json
import shutil
import sys
from pathlib import Path


FIXTURES = {"offers-sample.json": "offers-sample.json", "sample.json": "best-supplier-sample.json"}


def replace(path, before, after):
    source = path.read_text()
    if after in source:
        return
    if source.count(before) != 1:
        raise SystemExit(f"Hosted release text changed in {path.name}. Review its fixture labels.")
    path.write_text(source.replace(before, after, 1))


def stage(source, fixture_dir):
    suppliers = source / "web/src/suppliers"
    for original, fictional in FIXTURES.items():
        shutil.copyfile(fixture_dir / fictional, suppliers / original)
    replace(
        suppliers / "Offers.tsx",
        '{example ? "Example with sample replies, not live prices. " : ""}Every offer the suppliers sent, with price and timing. You decide; the mail agent tells the supplier.',
        '{example ? "Fictional offers for this example. Decisions stay in this browser." : "Offers from the latest supplier replies. The mail agent sends your decision."}',
    )
    replace(
        suppliers / "BestSupplier.tsx",
        '{example ? "Example with sample replies." : "From the latest supplier replies."} In live mode the mail agent sends these emails by itself, only to the case suppliers.',
        '{example ? "Fictional suppliers illustrate how availability and delivery affect the ranking." : "From the latest supplier replies."}',
    )
    replace(source / "web/src/main.tsx", '"Standard"} copy`).join',
            '"Standard"} copy${r.missCostConfirmed === false ? " (unconfirmed)" : ""}`).join')


def case_markers(node):
    if isinstance(node, dict):
        for key, item in node.items():
            if key in {"supplier", "excerpt", "draft_id", "body"} and isinstance(item, str) and len(item) >= 8:
                yield item
            yield from case_markers(item)
    if isinstance(node, list):
        for item in node:
            yield from case_markers(item)


def audit(repo, output):
    assets = output / "static/assets"
    public = [path for path in (output / "static").rglob("*") if path.is_file()]
    if not public or any(path.parent != assets or path.suffix not in {".css", ".js"} for path in public):
        raise SystemExit("Unexpected public asset. Review the prebuilt output before deployment.")
    bundle = "\n".join(path.read_text() for path in public if path.suffix == ".js")
    fixtures = Path(__file__).parent
    safe = {
        marker for fixture in FIXTURES.values()
        for marker in case_markers(json.loads((fixtures / fixture).read_text()))
    }
    for fixture in FIXTURES:
        raw = json.loads((repo / "web/src/suppliers" / fixture).read_text())
        for marker in set(case_markers(raw)) - safe:
            if marker in bundle or json.dumps(marker, ensure_ascii=False)[1:-1] in bundle:
                raise SystemExit("A case-derived supplier fixture value appears in the public bundle.")
    for marker in ("Fictional offers for this example", "Fictional suppliers illustrate", "(unconfirmed)"):
        if marker not in bundle:
            raise SystemExit("The hosted fixture labels or cost note are missing.")
    allowed = {"app.html", "login.html", "index.cjs", "live.cjs", ".vc-config.json", "replay.enc"}
    function = output / "functions/control.func"
    if {item.name for item in function.iterdir() if item.is_file()} != allowed or any(
        not item.is_file() for item in function.iterdir()
    ):
        raise SystemExit("Unexpected server function contents.")
    print("Verified the hosted bundle and encrypted package layout.")


if __name__ == "__main__":
    command, root, other = sys.argv[1:]
    {"stage": stage, "audit": audit}[command](Path(root), Path(other))
