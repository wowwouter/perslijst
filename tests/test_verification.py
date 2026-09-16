import csv
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import dns.exception
import dns.resolver

from verify_contacts import check_mail_domain, verify_file, verify_rows


class FakeResolver:
    def __init__(self, answers):
        self.answers = answers
        self.timeout = 10
        self.lifetime = 10

    def resolve(self, domain, record_type):
        value = self.answers[(domain, record_type)]
        if isinstance(value, BaseException):
            raise value
        return value


class VerificationTests(unittest.TestCase):
    def test_domain_statuses_distinguish_mail_routes_and_failures(self):
        resolver = FakeResolver({
            ("mx.example", "MX"): [SimpleNamespace(exchange="mail.mx.example.")],
            ("implicit.example", "MX"): dns.resolver.NoAnswer(),
            ("implicit.example", "A"): ["192.0.2.1"],
            ("null.example", "MX"): [SimpleNamespace(exchange=".")],
            ("missing.example", "MX"): dns.resolver.NXDOMAIN(),
            ("timeout.example", "MX"): dns.exception.Timeout(),
            ("none.example", "MX"): dns.resolver.NoAnswer(),
            ("none.example", "A"): dns.resolver.NoAnswer(),
            ("none.example", "AAAA"): dns.resolver.NoAnswer(),
        })
        self.assertEqual(check_mail_domain("mx.example", resolver), "mx_aanwezig")
        self.assertEqual(check_mail_domain("implicit.example", resolver), "geen_mx_wel_adresrecord")
        self.assertEqual(check_mail_domain("null.example", resolver), "null_mx_geen_mail")
        self.assertEqual(check_mail_domain("missing.example", resolver), "domein_bestaat_niet")
        self.assertEqual(check_mail_domain("timeout.example", resolver), "dns_controle_mislukt")
        self.assertEqual(check_mail_domain("none.example", resolver), "geen_mailroute_gevonden")

    def test_rows_keep_source_and_domain_checks_separate(self):
        resolver = FakeResolver({
            ("medium.example", "MX"): [SimpleNamespace(exchange="mail.medium.example.")],
        })
        rows = verify_rows([
            {"email": "redactie@medium.example", "bron_url": "https://medium.example/contact"},
            {"email": "info@medium.example", "bron_url": ""},
        ], resolver=resolver, timestamp="2026-09-16T00:00:00+00:00")
        self.assertEqual(rows[0]["bronverificatie"], "bevestigd_op_mediawebsite")
        self.assertEqual(rows[0]["maildomein_status"], "mx_aanwezig")
        self.assertEqual(rows[0]["verificatiestatus"], "officieel_gepubliceerd_en_mailroute_gevonden")
        self.assertEqual(rows[1]["verificatiestatus"], "bron_niet_bevestigd")

    def test_file_is_extended_without_losing_existing_columns(self):
        resolver = FakeResolver({
            ("medium.example", "MX"): [SimpleNamespace(exchange="mail.medium.example.")],
        })
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contacts.csv"
            path.write_text(
                "medium,email,bron_url\nKrant,redactie@medium.example,https://medium.example/contact\n",
                encoding="utf-8",
            )
            verify_file(path, resolver=resolver)
            with path.open(encoding="utf-8-sig", newline="") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["medium"], "Krant")
            self.assertEqual(row["maildomein"], "medium.example")
            self.assertEqual(row["verificatiestatus"], "officieel_gepubliceerd_en_mailroute_gevonden")


if __name__ == "__main__":
    unittest.main()
