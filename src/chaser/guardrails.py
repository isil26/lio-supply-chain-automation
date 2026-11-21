from dataclasses import dataclass

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
        return GuardrailResult(not errors, tuple(errors))
