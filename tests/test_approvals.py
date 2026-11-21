import json
import tempfile
import unittest
from pathlib import Path

from src.decide import approvals as ap

NOW = "2026-11-21T20:30:00+01:00"
EV = ["source doc"]


def deleg(**kw):
    d = {"id": "DEL-T", "delegator": "Dr. Maren Vogt", "delegate": "system",
         "action_kinds": ["supplier_info_request", "hold_and_quote", "purchase_order", "air_freight"],
         "max_value_eur": 2_000_000, "valid_from": "2026-11-21T20:00:00+01:00", "valid_until": "2026-11-22T20:00:00+01:00",
         "conditions": {"information_only": True, "reversible": True, "hold_and_quote": True},
         "source": {"who": "x", "when": "y", "medium": "mail"}, "confirmed_in_writing": True}
    d.update(kw)
    return d


def act(**kw):
    a = {"id": "A1", "kind": "supplier_info_request", "value_eur": 0, "category": "Game Media", "binding": False,
         "reversible": True, "evidence": EV}
    a.update(kw)
    return a


class ValueLadder(unittest.TestCase):
    def test_limits(self):
        cases = [(49_999, "Felix Brunner"), (50_000, "Tobias Brandt"), (499_999, "Tobias Brandt"),
                 (500_000, "Dr. Maren Vogt"), (1_999_999, "Dr. Maren Vogt"), (2_000_000, "Jonas Lindqvist"),
                 (4_999_999, "Jonas Lindqvist"), (5_000_000, "Jonas Lindqvist + Henrik Dahl")]
        for v, who in cases:
            r = ap.evaluate(act(kind="purchase_order", value_eur=v, binding=True, reversible=False), NOW, [])
            self.assertEqual(r["approver"]["name"], who, v)
            self.assertEqual(r["mode"], ap.ONE_CLICK)

    def test_cpo_and_cfo_both_required_and_unavailable_cfo_is_never(self):
        r = ap.evaluate(act(kind="purchase_order", value_eur=6_000_000, binding=True), NOW, [])
        self.assertEqual(r["required_signers"], ["Jonas Lindqvist", "Henrik Dahl"])
        r = ap.evaluate(act(kind="purchase_order", value_eur=6_000_000, binding=True), NOW, [], unavailable=["Henrik Dahl"])
        self.assertEqual(r["mode"], ap.NEVER)

    def test_art_book_buyer(self):
        r = ap.evaluate(act(kind="hold_and_quote", value_eur=12_390, category="Print & Packaging"), NOW, [])
        self.assertEqual((r["mode"], r["approver"]["name"]), (ap.ONE_CLICK, "Paul Winter"))

    def test_proposed_lower_role_over_limit_escalates(self):
        r = ap.evaluate(act(kind="purchase_order", value_eur=80_000, binding=True, approver_role="buyer"), NOW, [])
        self.assertEqual(r["mode"], ap.ESCALATE)
        self.assertEqual(r["approver"]["name"], "Tobias Brandt")


class Specials(unittest.TestCase):
    def test_air_freight(self):
        r = ap.evaluate(act(kind="air_freight", value_eur=150_000, binding=True, reversible=False), NOW, [])
        self.assertEqual((r["mode"], r["approver"]["name"], r["sla_minutes"]), (ap.ONE_CLICK, "Tobias Brandt", 30))
        r = ap.evaluate(act(kind="air_freight", value_eur=250_000, binding=True), NOW, [])
        self.assertEqual((r["mode"], r["approver"]["name"], r["sla_minutes"]), (ap.ESCALATE, "Jonas Lindqvist", 15))

    def test_air_freight_month_to_date_counts(self):
        r = ap.evaluate(act(kind="air_freight", value_eur=60_000, month_to_date_eur=150_000, binding=True), NOW, [])
        self.assertEqual(r["approver"]["name"], "Jonas Lindqvist")

    def test_dock_slot_and_deputy_when_silent_or_absent(self):
        a = act(kind="dock_slot", binding=True)
        self.assertEqual(ap.evaluate(a, NOW, [])["approver"]["name"], "Katrin Jansen")
        r = ap.evaluate({**a, "requested_at": "2026-11-21T20:00:00+01:00"}, "2026-11-21T20:31:00+01:00", [])
        self.assertEqual((r["mode"], r["approver"]["name"]), (ap.ESCALATE, "Raj Patel"))
        r = ap.evaluate(a, NOW, [], unavailable=["Katrin Jansen"])
        self.assertEqual((r["mode"], r["approver"]["name"]), (ap.ESCALATE, "Raj Patel"))

    def test_quality_never_even_with_confirmed_delegation(self):
        r = ap.evaluate(act(kind="quality_exception", category="Collector's Items", binding=True), NOW,
                        [deleg(action_kinds=list(ap.KINDS))])
        self.assertEqual(r["mode"], ap.NEVER)
        self.assertEqual(r["approver"]["name"], "Clara Weiss")
        self.assertEqual({"Clara Weiss", "Daniel Okafor", "Dr. Maren Vogt"}, set(r["required_signers"]))

    def test_vacancy_route_for_collectors_and_after_start(self):
        a = act(kind="air_freight", value_eur=50_000, category="Collector's Items", binding=True)
        r = ap.evaluate(a, NOW, [])
        self.assertEqual((r["mode"], r["approver"]["name"]), (ap.ESCALATE, "Dr. Maren Vogt"))
        self.assertTrue(any("PP-07 §6" in x for x in r["policy_refs"]))
        r = ap.evaluate(a, "2026-11-23T09:00:00+01:00", [])
        self.assertEqual((r["mode"], r["approver"]["name"]), (ap.ONE_CLICK, "Arjun Krishnan"))

    def test_supplier_release_pune_vacancy_with_okafor(self):
        r = ap.evaluate(act(kind="supplier_release", category="Collector's Items", binding=True,
                            conditional_release_expired=True, supplier="Pune"), NOW, [])
        self.assertEqual((r["mode"], r["approver"]["name"]), (ap.ESCALATE, "Dr. Maren Vogt"))
        self.assertEqual([s["name"] for s in r["co_signers"]], ["Daniel Okafor"])
        self.assertTrue(any("2026-10-30" in b for b in r["blocked_by"]))


class NeverRules(unittest.TestCase):
    def test_missing_evidence(self):
        r = ap.evaluate(act(evidence=[]), NOW, [deleg()])
        self.assertEqual(r["mode"], ap.NEVER)

    def test_reveals_walkaway_or_slack(self):
        for phrase in ("our walkaway price is 10", "we have slack of 2 days", "maximum premium EUR 4"):
            r = ap.evaluate(act(draft=phrase), NOW, [deleg()])
            self.assertEqual(r["mode"], ap.NEVER, phrase)

    def test_missing_value_for_po(self):
        r = ap.evaluate(act(kind="purchase_order", value_eur=None, binding=True), NOW, [])
        self.assertEqual(r["mode"], ap.NEVER)

    def test_unknown_kind(self):
        self.assertEqual(ap.evaluate({"kind": "wire_money"}, NOW, [])["mode"], ap.NEVER)


class Delegation(unittest.TestCase):
    def test_simulated_grants_require_explicit_replay(self):
        grant = deleg(id="DEL-TEST-example", simulated=True)
        self.assertEqual(ap.evaluate(act(), NOW, [grant])["mode"], ap.ONE_CLICK)
        replay = ap.evaluate(act(), NOW, [grant], allow_simulated=True)
        self.assertEqual((replay["mode"], replay["delegation_id"]), (ap.AUTO, grant["id"]))
        self.assertTrue(replay["simulated"])
        self.assertIn("Simulated approval", replay["reason"])

    def test_confirmed_covers_info_request_auto(self):
        r = ap.evaluate(act(), NOW, [deleg()])
        self.assertEqual((r["mode"], r["delegation_id"]), (ap.AUTO, "DEL-T"))
        self.assertIn("approved by delegation of Dr. Maren Vogt, record DEL-T", r["reason"])

    def test_unconfirmed_never_auto(self):
        r = ap.evaluate(act(), NOW, [deleg(confirmed_in_writing=False)])
        self.assertEqual(r["mode"], ap.ONE_CLICK)
        self.assertIn("delegation unconfirmed", r["notes"])
        self.assertEqual(r["delegation_id"], "DEL-T")

    def test_seed_is_unconfirmed_and_one_click(self):
        # the repo file also holds SIMULATED test-case delegations (DEL-TEST-*); the real seed is DEL-001 only
        seed = [d for d in ap.load_delegations() if not d.get("simulated")]
        self.assertEqual(len(seed), 1)
        self.assertFalse(seed[0]["confirmed_in_writing"])
        self.assertEqual(seed[0]["max_value_eur"], 2_000_000)
        self.assertEqual(ap.evaluate(act(), NOW, seed)["mode"], ap.ONE_CLICK)

    def test_limit_is_strict_and_binding_never_auto(self):
        self.assertEqual(ap.evaluate(act(kind="hold_and_quote", value_eur=1_999_999), NOW, [deleg()])["mode"], ap.AUTO)
        r = ap.evaluate(act(kind="hold_and_quote", value_eur=2_000_000), NOW, [deleg()])
        self.assertEqual((r["mode"], r["approver"]["name"], r["delegation_id"]), (ap.ONE_CLICK, "Jonas Lindqvist", None))
        r = ap.evaluate(act(kind="purchase_order", value_eur=900_000, binding=True, reversible=False), NOW, [deleg()])
        self.assertEqual(r["mode"], ap.ONE_CLICK)
        self.assertIsNone(r["delegation_id"])

    def test_expired_revoked_and_not_yet_valid(self):
        self.assertEqual(ap.evaluate(act(), "2026-11-22T21:00:00+01:00", [deleg()])["mode"], ap.ONE_CLICK)
        self.assertEqual(ap.evaluate(act(), NOW, [deleg(revoked_at=NOW)])["mode"], ap.ONE_CLICK)
        self.assertEqual(ap.evaluate(act(), NOW, [deleg(valid_from="2026-11-22T00:00:00+01:00")])["mode"], ap.ONE_CLICK)

    def test_delegation_cannot_create_authority(self):
        d = deleg(delegator="Felix Brunner")  # a buyer cannot delegate a Category Lead level decision
        r = ap.evaluate(act(kind="hold_and_quote", value_eur=300_000), NOW, [d])
        self.assertNotEqual(r["mode"], ap.AUTO)
        r = ap.evaluate(act(kind="dock_slot", binding=False), NOW, [deleg(action_kinds=["dock_slot"])])
        self.assertNotEqual(r["mode"], ap.AUTO)

    def test_kill_switch(self):
        self.assertEqual(ap.evaluate(act(), NOW, [deleg()], kill_switch=True)["mode"], ap.ONE_CLICK)

    def test_add_confirm_revoke_helpers(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "d.json"
            p.write_text(json.dumps({"delegations": []}))
            rec = ap.add_delegation({"delegator": "Dr. Maren Vogt", "action_kinds": ["supplier_info_request"],
                                     "max_value_eur": 1000, "valid_from": "2026-11-21T20:00:00+01:00", "valid_until": "2026-11-22T20:00:00+01:00",
                                     "source": {"who": "Felix", "when": NOW, "medium": "mail"}}, p)
            self.assertFalse(rec["confirmed_in_writing"])
            self.assertEqual(ap.evaluate(act(), NOW, ap.load_delegations(p))["mode"], ap.ONE_CLICK)
            ap.confirm_delegation(rec["id"], "mail 21 Nov 21:00", NOW, p)
            self.assertEqual(ap.evaluate(act(), NOW, ap.load_delegations(p))["mode"], ap.AUTO)
            ap.revoke_delegation(rec["id"], "Dr. Maren Vogt", NOW, p)
            self.assertEqual(ap.evaluate(act(), NOW, ap.load_delegations(p))["mode"], ap.ONE_CLICK)
            with self.assertRaises(ValueError):
                ap.add_delegation({"delegator": "x", "action_kinds": ["nonsense"], "max_value_eur": 1,
                                   "valid_until": NOW, "source": "s"}, p)


class SlaAndLog(unittest.TestCase):
    def test_sla_escalation_steps(self):
        a = act(kind="hold_and_quote", value_eur=12_390, category="Print & Packaging", requested_at="2026-11-21T20:00:00+01:00")
        self.assertEqual(ap.evaluate(a, "2026-11-21T20:29:00+01:00", [])["mode"], ap.ONE_CLICK)
        r = ap.evaluate(a, "2026-11-21T20:31:00+01:00", [])
        self.assertEqual((r["mode"], r["approver"]["name"]), (ap.ESCALATE, "Sofia Marchetti"))
        r = ap.evaluate(a, "2026-11-21T21:01:00+01:00", [])
        self.assertEqual(r["approver"]["name"], "Dr. Maren Vogt")

    def test_cpo_air_freight_15_minute_sla(self):
        a = act(kind="air_freight", value_eur=250_000, binding=True, requested_at="2026-11-21T20:00:00+01:00")
        r = ap.evaluate(a, "2026-11-21T20:16:00+01:00", [])
        self.assertEqual((r["mode"], r["approver"]["name"]), (ap.ESCALATE, "Henrik Dahl"))

    def test_audit_log_auto_never_as_person(self):
        con = ap.connect(":memory:")
        ev = ap.submit(con, act(id="X1"), NOW, [deleg()])
        self.assertEqual(ev["mode"], ap.AUTO)
        row = ap.log_rows(con, "X1")[0]
        self.assertEqual((row["decided_by"], row["delegation_id"]), ("delegation", "DEL-T"))
        self.assertTrue(row["reason"].startswith("approved by delegation of Dr. Maren Vogt, record DEL-T"))
        with self.assertRaises(ValueError):
            ap.log_decision(con, "X2", ap.AUTO, "Dr. Maren Vogt", None, "delegation", "x")  # needs record id
        with self.assertRaises(ValueError):
            ap.log_decision(con, "X2", ap.AUTO, "x", None, "nobody", "x")

    def test_pending_human_decision_and_permissions(self):
        con = ap.connect(":memory:")
        a = act(id="P1", kind="hold_and_quote", value_eur=12_390, category="Print & Packaging")
        ap.submit(con, a, NOW, [])
        with self.assertRaises(PermissionError):
            ap.record_human_decision(con, "P1", "Mei Lin", "approve", "", NOW)
        res = ap.record_human_decision(con, "P1", "Paul Winter", "approve", "ok", NOW)
        self.assertEqual(res["status"], "approved")
        rows = ap.log_rows(con, "P1")
        self.assertEqual((rows[-1]["mode"], rows[-1]["decided_by"], rows[-1]["approver"]), ("APPROVED", "human", "Paul Winter"))

    def test_multi_signer_needs_all(self):
        con = ap.connect(":memory:")
        a = act(id="S1", kind="supplier_release", category="Collector's Items", binding=True)
        ap.submit(con, a, NOW, [])
        r = ap.record_human_decision(con, "S1", "Daniel Okafor", "approve", "", NOW)
        self.assertEqual((r["status"], r["waiting_for"]), ("pending", ["Dr. Maren Vogt"]))
        self.assertEqual(ap.record_human_decision(con, "S1", "Dr. Maren Vogt", "approve", "", NOW)["status"], "approved")

    def test_escalate_due(self):
        con = ap.connect(":memory:")
        ap.submit(con, act(id="D1", kind="dock_slot", binding=True), NOW, [])
        self.assertEqual(ap.escalate_due(con, "2026-11-21T20:40:00+01:00"), [])
        due = ap.escalate_due(con, "2026-11-21T21:05:00+01:00")
        self.assertEqual([d["action_id"] for d in due], ["D1"])
        self.assertEqual(due[0]["next_approver"]["name"], "Raj Patel")
        self.assertIn("Raj Patel", due[0]["reminder"])
        self.assertEqual(ap.escalate_due(con, "2026-11-21T21:06:00+01:00"), [])  # not logged twice
        self.assertEqual(ap.log_rows(con, "D1")[-1]["decided_by"], "system-escalated")

    def test_reminder_auto_text(self):
        ev = ap.evaluate(act(), NOW, [deleg()])
        self.assertIn("under your delegation DEL-T", ap.reminder_text(act(), ev))


class PolicyCheck(unittest.TestCase):
    def test_wrong_approver_and_forbidden(self):
        a = act(kind="purchase_order", value_eur=900_000, binding=True, status="approved", approved_by="Paul Winter (Buyer)")
        self.assertFalse(ap.policy_check(a, NOW, [])["ok"])
        a["approved_by"] = "Dr. Maren Vogt"
        self.assertTrue(ap.policy_check(a, NOW, [])["ok"])
        self.assertFalse(ap.policy_check(act(draft="our walkaway is 5"), NOW, [])["ok"])


if __name__ == "__main__":
    unittest.main()
