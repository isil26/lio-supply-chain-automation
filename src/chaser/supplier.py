import csv
from pathlib import Path

from .models import Supplier


ROOT = Path(__file__).resolve().parents[2]


def load_supplier(supplier_id: str, data_root: Path | None = None) -> Supplier:
    root = (data_root or ROOT / "data") / "suppliers"
    matches = list(root.glob(f"{supplier_id}_*/profile.csv"))
    if len(matches) != 1:
        raise ValueError(f"{supplier_id}: expected one profile.csv, found {len(matches)}")
    with matches[0].open("r", encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))
    language = (row.get("preferred_language") or "en").strip().lower()
    if language not in {"ko", "zh", "pl", "en"}:
        language = "en"
    return Supplier(
        supplier_id=row["supplier_id"].strip(),
        name=row["name"].strip(),
        contact_name=row.get("contact_name", "").strip(),
        contact_email=row["contact_email"].strip(),
        preferred_language=language,
        phone=row.get("phone", "").strip(),
    )
