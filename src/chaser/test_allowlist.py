import os
import unittest
from unittest import mock

from .allowlist import check_recipient
from .outbox import SMTPOutbox


class AllowlistTest(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop("CHASER_ALLOWED_DOMAINS", None)
        os.environ.pop("CHASER_ALLOWED_RECIPIENTS", None)

    def tearDown(self):
        self.env.stop()

    def test_supplier_domain_allowed(self):
        self.assertEqual(check_recipient("Chen Jie <Chen.Jie.dg-precision@suppliers.juliansibbing.de>"),
                         "chen.jie.dg-precision@suppliers.juliansibbing.de")

    def test_other_address_refused(self):
        for bad in ("someone@gmail.com", "x@suppliers.juliansibbing.de.evil.com", "", "not-an-address"):
            with self.assertRaises(PermissionError):
                check_recipient(bad)

    def test_exact_override(self):
        os.environ["CHASER_ALLOWED_RECIPIENTS"] = "test@team.example"
        self.assertEqual(check_recipient("test@team.example"), "test@team.example")

    def test_smtp_outbox_refuses_before_connecting(self):
        os.environ["CHASER_SMTP_HOST"] = "smtp.invalid"
        with mock.patch("smtplib.SMTP") as smtp:
            with self.assertRaises(PermissionError):
                SMTPOutbox().send(thread_id="t", sender="a@b.c", recipient="boss@gmail.com", subject="s", body="b")
            smtp.assert_not_called()


if __name__ == "__main__":
    unittest.main()
