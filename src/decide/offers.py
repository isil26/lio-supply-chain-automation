"""Resolve explicitly versioned supplier quotes while retaining their source facts."""

from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class Revision:
    source: str
    revision: str | None
    supersedes: set[str]
    offers: list[dict]
    evidence: list[dict]


def active_revision(candidates):
    """Require one explicit chain covering every known revision of the quote."""
    by_revision = {candidate.revision: candidate for candidate in candidates}
    if None in by_revision or len(by_revision) != len(candidates):
        return None
    if any(len(candidate.supersedes) > 1 for candidate in candidates):
        return None
    superseded = set().union(*(candidate.supersedes for candidate in candidates))
    heads = by_revision.keys() - superseded
    if len(heads) != 1:
        return None
    head = by_revision[heads.pop()]
    reached = set()
    current = head
    while current and current.revision not in reached:
        reached.add(current.revision)
        current = by_revision.get(next(iter(current.supersedes), None))
    return head if not current and reached == by_revision.keys() else None


def quote_identity(entry):
    return entry["value"]["offer_id"], entry["value"]["revision"]


def select_offers(docs):
    """Return current quotes and cited revision conflicts for Procurement."""
    active, groups = defaultdict(list), defaultdict(list)
    seen = set()
    for doc in docs:
        fields, source = doc["fields"], doc["source"]
        supplier, digest = doc.get("supplier_id"), doc.get("sha")
        offers = fields.get("available_offer", [])
        headings = fields.get("offer_revision", [])
        if not (offers or headings):
            continue
        if supplier and digest:
            fingerprint = supplier, digest
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
        if not headings or not supplier:
            active[source].extend(offers)
            continue

        headings_by_quote, identities_by_page = defaultdict(list), defaultdict(set)
        for entry in headings:
            key = quote_identity(entry)
            headings_by_quote[key].append(entry["citation"])
            identities_by_page[entry["citation"].get("page")].add(key)
        offers_by_quote, ambiguous = defaultdict(list), set()
        for offer in offers:
            keys = identities_by_page.get(offer["citation"].get("page")) or headings_by_quote.keys()
            if len(keys) > 1:
                ambiguous.update(keys)
            for key in keys:
                offers_by_quote[key].append(offer)
        supersessions = defaultdict(list)
        for entry in fields.get("offer_supersession", []):
            supersessions[quote_identity(entry)].append(entry)

        for (offer_id, revision), evidence in headings_by_quote.items():
            key = offer_id, revision
            statements = supersessions[key]
            groups[supplier, offer_id].append(Revision(
                source, None if key in ambiguous else revision,
                {entry["value"]["supersedes"] for entry in statements},
                offers_by_quote[key], [*evidence, *(entry["citation"] for entry in statements)],
            ))

    conflicts = []
    for (supplier, offer_id), candidates in groups.items():
        current = active_revision(candidates)
        if current:
            active[current.source].extend(dict(offer, revision_evidence=current.evidence) for offer in current.offers)
        else:
            materials = {offer["value"]["material"] for row in candidates for offer in row.offers}
            evidence = [citation for row in candidates
                        for citation in (*row.evidence, *(offer["citation"] for offer in row.offers))]
            conflicts.append((supplier, offer_id, materials, evidence))
    return active, conflicts
