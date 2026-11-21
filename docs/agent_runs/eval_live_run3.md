# Agent evaluation report

| Scenario | Runs | Pass rate | Violations |
|---|---:|---:|---|
| air_lot_priority | 1 | 100% | none |
| art_book_shortfall | 1 | 100% | none |
| email_without_approval | 1 | 0% | none |
| game_card_short_ship | 1 | 100% | none |
| hallucinated_number | 1 | 0% | none |
| sleeve_revision_conflict | 1 | 100% | none |
| statue_quality_hold | 1 | 0% | stop_check |
| unseen_german_notice | 1 | 100% | none |

## Guard detail

| Scenario | Rule | Pass rate | Evidence |
|---|---|---:|---|
| air_lot_priority | numeric_grounding | 100% | none |
| air_lot_priority | citation_check | 100% | none |
| air_lot_priority | stop_check | 100% | none |
| art_book_shortfall | numeric_grounding | 100% | none |
| art_book_shortfall | citation_check | 100% | none |
| art_book_shortfall | policy_check | 100% | none |
| art_book_shortfall | stop_check | 100% | none |
| art_book_shortfall | language_check | 100% | none |
| email_without_approval | policy_check | 0% | none |
| game_card_short_ship | numeric_grounding | 100% | none |
| game_card_short_ship | citation_check | 100% | none |
| game_card_short_ship | stop_check | 100% | none |
| hallucinated_number | numeric_grounding | 0% | none |
| hallucinated_number | citation_check | 0% | none |
| sleeve_revision_conflict | numeric_grounding | 100% | none |
| sleeve_revision_conflict | citation_check | 100% | none |
| sleeve_revision_conflict | policy_check | 100% | none |
| sleeve_revision_conflict | stop_check | 100% | none |
| statue_quality_hold | policy_check | 100% | none |
| statue_quality_hold | citation_check | 100% | none |
| statue_quality_hold | stop_check | 0% | {"tools": ["release_gate_status"]} |
| unseen_german_notice | policy_check | 100% | none |
| unseen_german_notice | citation_check | 100% | none |
| unseen_german_notice | stop_check | 100% | none |
