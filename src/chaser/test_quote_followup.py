import json
import sqlite3
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

from src.chaser import autosend, deals, exchange_rates, quote_followup
from src.chaser import test_mail_plan as fixtures


class QuoteFlowTest(unittest.TestCase):
    setUp = fixtures.MailPlanningTest.setUp
    add_thread = fixtures.MailPlanningTest.add_thread
    receive = fixtures.MailPlanningTest.receive
    promise_forecast = fixtures.MailPlanningTest.promise_forecast
    clock = datetime(2031,8,9,12,tzinfo=timezone.utc)
    deadline = '2031-08-12T12:00:00+00:00'

    def sync(self):
        deals.sync(self.db,self.deadline,now=self.clock,model=False)

    def receipt(self, ref,when):
        with self.db:
            self.db.execute("""INSERT INTO messages(chase_id,external_id,side,sender,body,time,transport)
                SELECT id,?,'out','buyer@example.test',body,?,? FROM chases WHERE id=?""",
                (f"<sent-{ref}>",when.isoformat(),json.dumps({"mode":"smtp","status":"smtp_accepted"}),ref))
            self.db.execute("UPDATE chases SET status='awaiting reply' WHERE id=?",(ref,))

    def test_collect_and_reconfirm_missing_terms_without_a_buyer(self):
        from email.message import EmailMessage
        self.promise_forecast()
        self.receive('A1','Quantity: 24 units. USD 3.50 per unit.','partial')
        self.sync()
        quote_followup.prepare(self.db,self.clock)
        quote_followup.prepare(self.db,self.clock)
        chase,=self.db.execute("SELECT * FROM chases WHERE status='quote draft'")
        self.assertTrue(quote_followup.current(self.db,chase,self.clock))
        self.assertIn("still need delivery date and time",chase["body"])
        self.assertIn("3.5 USD",chase["body"])
        self.assertFalse(autosend.binding(chase['body']))
        self.receipt(chase['id'],self.clock)
        self.assertEqual(next(iter(quote_followup.plans(self.db,self.clock).values()))['state'],'sent')
        msg=EmailMessage()
        msg['Subject']=chase['subject'];msg['From']=chase['address'];msg['To']='team@example.test'
        msg['Message-ID']='<complete>';msg['In-Reply-To']=f"<sent-{chase['id']}>"
        msg['Date']='Sat, 09 Aug 2031 13:00:00 +0000'
        msg.set_content('All other terms remain unchanged. Delivery: 2031-08-10, 18:00 CET. AWB 020-12345678.')
        from src import chaser
        self.assertTrue(chaser.receive(self.db,msg))
        self.sync()
        d,=deals.list_deals(self.db)['deals']
        self.assertEqual((d['quantity'],d['unit_price'],d['currency'],d['eligible']),(24,3.5,'USD',1))
        self.assertIn('18:00',d['eta'])
        self.assertTrue(d['drafts']['approve']['body'])
        self.assertFalse(quote_followup.plans(self.db,self.clock))
        self.assertFalse(quote_followup.current(self.db,chase,self.clock))

    def test_normal_mail_cycle_dispatches_one_information_request(self):
        import os
        self.promise_forecast()
        self.receive("A1","Quantity: 24 units. Delivery: 2031-08-10 16:00 UTC.","no-price")
        now=self.clock
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):
                return now
        env={"CHASER_REAL_SMTP":"1","CHASER_SENDER":"buyer@example.test","CHASER_SMTP_HOST":"test.invalid",
             "CHASER_AUTO_SEND":"1","CHASER_AUTO_COOLDOWN_MIN":"0"}
        with patch.dict(os.environ,env), patch("src.chaser.mailenv.load_team_mail_env"), patch("src.chaser.datetime",Clock), patch(
              "src.chaser.deadlines.datetime",Clock), patch("src.chaser.smtplib.SMTP") as smtp:
            client=smtp.return_value.__enter__.return_value
            client.send_message.return_value={}
            autosend.run(self.db,now=now)
            autosend.run(self.db,now=now)
            self.assertEqual(client.send_message.call_count,1)
            sent=client.send_message.call_args.args[0]
            self.assertEqual(sent["In-Reply-To"],"<no-price>")
            self.assertIn("still need unit price and currency",sent.get_content())
            self.assertNotIn("reserve",sent.get_content().lower())

    def test_one_reminder_and_no_contact_after_refusal_or_covered_demand(self):
        self.promise_forecast()
        self.receive('A1','USD 3.50 per unit.','partial')
        self.sync()
        quote_followup.prepare(self.db,self.clock)
        first,=self.db.execute("SELECT * FROM chases WHERE status='quote draft'")
        self.receipt(first['id'],self.clock)
        later=self.clock+timedelta(hours=14)
        quote_followup.prepare(self.db,later)
        reminder,=self.db.execute("SELECT * FROM chases WHERE status='quote draft'")
        self.assertNotEqual(first['id'],reminder['id'])
        self.assertIn('Following up',reminder['body'])
        self.receipt(reminder['id'],later)
        quote_followup.prepare(self.db,later+timedelta(hours=14))
        self.assertFalse(self.db.execute("SELECT 1 FROM chases WHERE status='quote draft'").fetchone())
        self.promise_forecast(gap=0)
        self.assertEqual(next(iter(quote_followup.plans(self.db,later).values()))['state'],'covered')
        self.promise_forecast()
        self.receive('A1','We cannot supply any units before launch.','refused',14)
        self.sync()
        self.assertEqual(next(iter(quote_followup.plans(self.db,later).values()))['state'],'closed')

    def test_earlier_promise_and_unverified_reply_are_never_sent(self):
        self.promise_forecast()
        self.receive('A1','We will send the quotation tomorrow morning CET.','promise')
        self.sync()
        p,=quote_followup.plans(self.db,self.clock).values()
        self.assertEqual(p['state'],'scheduled')
        self.assertEqual(datetime.fromisoformat(p['nextAt']).hour,12)
        self.db.execute("UPDATE messages SET sender='someone@example.test' WHERE external_id='<promise>'")
        self.assertEqual(next(iter(quote_followup.plans(self.db,self.clock).values()))['state'],'blocked')

    def test_legacy_enquiry_yields_to_actual_delivery_state(self):
        self.promise_forecast()
        self.receive('A1','USD 3.50 per unit.','partial')
        self.sync()
        d,=deals.list_deals(self.db)['deals']
        ref=deals.approve_request(self.db,d['id'],d['revision'],'Buyer','Can you confirm the remaining terms?')
        def plan(at):
            return next(iter(quote_followup.plans(self.db,at).values()))
        self.assertEqual(plan(self.clock)['state'],'queued')
        self.db.execute("UPDATE chases SET status='duplicate' WHERE id=?",(ref,))
        self.assertEqual(plan(self.clock)['state'],'due')
        self.receipt(ref,self.clock)
        self.assertEqual(plan(self.clock)['state'],'sent')
        reminder=plan(self.clock+timedelta(hours=14))['candidate']
        self.assertIn('Following up',reminder[3])

    def test_explicit_refusal_for_this_deadline_stops_followups(self):
        self.promise_forecast()
        self.receive('A1','No quantity from this lot can reach Europe before 12 August at 14:00 CEST.','refusal')
        self.sync()
        self.assertEqual(next(iter(quote_followup.plans(self.db,self.clock).values()))['state'],'closed')
        self.receive('A1','No quantity from this lot can reach Europe before 11 August at 14:00 CEST.','other-day',10)
        self.sync()
        self.assertNotEqual(next(iter(quote_followup.plans(self.db,self.clock).values()))['state'],'closed')

    def test_actual_offer_with_a_separate_flat_freight_quote(self):
        self.promise_forecast()
        self.receive('A1','Quantity: 24 units. USD 3.50 per unit. Delivery: 2031-08-10 18:00 CET. '
                     'Additional freight charge: EUR 4. AWB 020-12345678. A written PO is required before dispatch.','firm')
        self.sync()
        d,=deals.list_deals(self.db)['deals']
        self.assertEqual((d['offer_kind'],d['eligible'],d['freight_charge'],d['total_eur']),('goods',1,4,81.28))


class RatesTest(unittest.TestCase):
    def document(self,date,usd):
        rates={'USD':usd,'CNY':7.2,'INR':100,'KRW':1500,'PLN':4.2}
        body=''.join(f'<Cube currency="{k}" rate="{v}"/>' for k,v in rates.items())
        return f'<Envelope xmlns="{exchange_rates.NAMESPACE[1:-1]}"><Cube time="{date}">{body}</Cube></Envelope>'.encode()

    def test_inverse_publication_cache_and_invalid_feed(self):
        db=sqlite3.connect(':memory:')
        self.assertEqual(exchange_rates.snapshot(db)['source'],'Planning estimate')
        clock=datetime(2026,11,22,tzinfo=timezone.utc)
        exchange_rates.refresh(db,self.document('2026-11-20',1.25),clock)
        exchange_rates.refresh(db,self.document('2026-11-19',1.5),clock)
        for val in (0,float('nan'),-1):
            with self.assertRaises(ValueError):
                exchange_rates.refresh(db,self.document('2026-11-21',val),clock)
        fx=exchange_rates.snapshot(db)
        self.assertEqual((fx['source'],fx['asOf'],fx['eurPerUnit']['USD']),('ECB','2026-11-20',0.8))
