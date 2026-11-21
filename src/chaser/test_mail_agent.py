import os
import unittest
from unittest import mock

from . import mail_agent

ENV = {name: "x" for name in mail_agent.REQUIRED}
ENV.update(CHASER_SENDER="team@example.test", CHASER_SMTP_HOST="smtp.example.test", SOONY_IMAP_HOST="imap.example.test")


class MailAgentTest(unittest.TestCase):
    def test_status_lists_missing(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(mail_agent.main(["status"]), 1)

    def test_check_signs_in_without_sending(self):
        with mock.patch.dict(os.environ, ENV, clear=True), \
             mock.patch("smtplib.SMTP") as smtp, mock.patch("imaplib.IMAP4_SSL") as imap:
            self.assertEqual(mail_agent.main(["check"]), 0)
            client = smtp.return_value.__enter__.return_value
            smtp.return_value.login.assert_called_once()
            client.send_message.assert_not_called()
            smtp.return_value.send_message.assert_not_called()
            imap.return_value.__enter__.return_value.login.assert_called_once()


if __name__ == "__main__":
    unittest.main()
