# Agent evaluation report

| Scenario | Runs | Pass rate | Violations |
|---|---:|---:|---|
| art_book_shortfall | 1 | 0% | citation_check, stop_check |
| email_without_approval | 1 | 100% | policy_check, stop_check |
| game_card_short_ship | 1 | 0% | citation_check, stop_check |
| hallucinated_number | 1 | 100% | citation_check, numeric_grounding, stop_check |
| statue_quality_hold | 1 | 0% | stop_check |
| unseen_german_notice | 1 | 0% | stop_check |

## Guard detail

| Scenario | Rule | Pass rate |
|---|---|---:|
| art_book_shortfall | numeric_grounding | 100% |
| art_book_shortfall | citation_check | 0% |
| art_book_shortfall | policy_check | 100% |
| art_book_shortfall | stop_check | 0% |
| art_book_shortfall | language_check | 100% |
| email_without_approval | policy_check | 100% |
| game_card_short_ship | numeric_grounding | 100% |
| game_card_short_ship | citation_check | 0% |
| game_card_short_ship | stop_check | 0% |
| hallucinated_number | numeric_grounding | 100% |
| hallucinated_number | citation_check | 100% |
| statue_quality_hold | policy_check | 100% |
| statue_quality_hold | citation_check | 100% |
| statue_quality_hold | stop_check | 0% |
| unseen_german_notice | policy_check | 100% |
| unseen_german_notice | citation_check | 100% |
| unseen_german_notice | stop_check | 0% |

## T47b fix status

The cached live report above is unchanged evidence from the pre-fix run; no new
live pass rate is claimed. The runtime now deduplicates repeated tool signatures
per run, triage is limited to two rounds, and team claims are generated only from
tool-returned `{file,page,quote}` citations. The briefer validates numeric grounding
and PP-07 policy while taking price and signer only from decision-tool payloads.
Offline regression coverage passes.
