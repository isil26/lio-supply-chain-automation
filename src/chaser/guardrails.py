from dataclasses import dataclass
import re

from .models import Issue


FORBIDDEN_COMMITMENTS = (
    "we guarantee",
    "guaranteed",
    "we commit",
    "will arrive",
    "is confirmed",
)


@dataclass(frozen=True)
class GuardrailResult:
    ok: bool
    errors: tuple[str, ...]


class Guardrails:
    def validate_issue(self, issue: Issue) -> GuardrailResult:
        errors = []
        if issue.max_price_premium_pct < 0:
            errors.append("max_price_premium_pct cannot be negative")
        if issue.proposed_price_premium_pct > issue.max_price_premium_pct:
            errors.append(
                "proposed price premium exceeds max_price_premium_pct "
                f"({issue.proposed_price_premium_pct:.2f}% > {issue.max_price_premium_pct:.2f}%)"
            )
        return GuardrailResult(not errors, tuple(errors))

    def validate_draft(self, body: str) -> GuardrailResult:
        lowered = body.lower()
        errors = [f"binding commitment phrase: {phrase}" for phrase in FORBIDDEN_COMMITMENTS
                  if phrase in lowered]
        forbidden_disclosures = (
            (r"\bdeadline\s+(?:slack|buffer)\b", "deadline slack"),
            (r"\b(?:we|our)\s+(?:have|retain)\s+\d+\s*(?:hours?|days?)\s+(?:of\s+)?(?:slack|buffer)\b", "deadline slack"),
            (r"\b(?:maximum|max(?:imum)?\s+price)\s+premium\b|\bpremium\s+(?:ceiling|cap|maximum|limit)\b", "maximum premium"),
            (r"\b(?:we\s+can\s+(?:pay|offer)\s+(?:up\s+to|a\s+maximum)|maximum\s+(?:premium|price))\b", "maximum premium"),
            (r"\bcost\s+(?:per|of)\s+(?:a\s+)?(?:missing|missed)\s+(?:copy|unit)\b", "cost per missing copy"),
            (r"\b(?:walk[- ]?away|walkaway)\b|\balternative\s+suppliers?\b", "walkaway or alternative supplier"),
        )
        for pattern, label in forbidden_disclosures:
            if re.search(pattern, lowered):
                errors.append(f"draft reveals {label}")
        return GuardrailResult(not errors, tuple(errors))
