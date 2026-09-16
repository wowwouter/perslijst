"""Add source and mail-domain verification to a crawl result.

This deliberately does not probe individual mailboxes. SMTP recipient checks are
frequently disabled or deliberately inconclusive. The source page and DNS status
are recorded separately so the result does not overclaim deliverability.
"""

import csv
import os
import sys
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import dns.exception
import dns.resolver


EXTRA_FIELDS = [
    "bronverificatie",
    "maildomein",
    "maildomein_status",
    "verificatiestatus",
    "geverifieerd_op",
]


def email_domain(email):
    parts = str(email).strip().lower().rsplit("@", 1)
    return parts[1] if len(parts) == 2 else ""


def check_mail_domain(domain, resolver=None):
    """Return a technical domain-level status without contacting a mailbox."""
    if not domain:
        return "ongeldig_emailadres"
    resolver = resolver or dns.resolver.Resolver()
    resolver.timeout = min(getattr(resolver, "timeout", 3.0), 3.0)
    resolver.lifetime = min(getattr(resolver, "lifetime", 5.0), 5.0)
    try:
        answers = resolver.resolve(domain, "MX")
        exchanges = [str(answer.exchange).rstrip(".") for answer in answers]
        if exchanges and any(exchange for exchange in exchanges):
            return "mx_aanwezig"
        return "null_mx_geen_mail"
    except dns.resolver.NXDOMAIN:
        return "domein_bestaat_niet"
    except dns.resolver.NoAnswer:
        pass
    except (dns.exception.Timeout, dns.resolver.NoNameservers, dns.resolver.LifetimeTimeout):
        return "dns_controle_mislukt"

    # SMTP permits an address record as an implicit mail route when MX is absent.
    for record_type in ("A", "AAAA"):
        try:
            if list(resolver.resolve(domain, record_type)):
                return "geen_mx_wel_adresrecord"
        except dns.resolver.NXDOMAIN:
            return "domein_bestaat_niet"
        except dns.resolver.NoAnswer:
            continue
        except (dns.exception.Timeout, dns.resolver.NoNameservers, dns.resolver.LifetimeTimeout):
            return "dns_controle_mislukt"
    return "geen_mailroute_gevonden"


def combined_status(source_status, domain_status):
    if source_status != "bevestigd_op_mediawebsite":
        return "bron_niet_bevestigd"
    if domain_status in {"mx_aanwezig", "geen_mx_wel_adresrecord"}:
        return "officieel_gepubliceerd_en_mailroute_gevonden"
    if domain_status in {"null_mx_geen_mail", "domein_bestaat_niet", "geen_mailroute_gevonden"}:
        return "officieel_gepubliceerd_geen_mailroute_gevonden"
    return "officieel_gepubliceerd_mailroute_onbekend"


def verify_rows(rows, resolver=None, timestamp=None):
    timestamp = timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds")
    domains = sorted({email_domain(row.get("email", "")) for row in rows})
    if resolver is not None:
        statuses = {domain: check_mail_domain(domain, resolver) for domain in domains}
    else:
        workers = min(max(int(os.environ.get("PRESS_DNS_WORKERS", "12")), 1), 32)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            statuses = dict(zip(domains, executor.map(check_mail_domain, domains)))
    for row in rows:
        domain = email_domain(row.get("email", ""))
        source_status = "bevestigd_op_mediawebsite" if row.get("bron_url") else "bron_niet_bevestigd"
        domain_status = statuses.get(domain, "ongeldig_emailadres")
        row.update({
            "bronverificatie": source_status,
            "maildomein": domain,
            "maildomein_status": domain_status,
            "verificatiestatus": combined_status(source_status, domain_status),
            "geverifieerd_op": timestamp,
        })
    return rows


def verify_file(input_path, output_path=None, resolver=None):
    input_path = Path(input_path)
    output_path = Path(output_path) if output_path else input_path
    with input_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or ())
        rows = list(reader)
    if "email" not in fieldnames:
        raise ValueError("De kolom email ontbreekt")
    for field in EXTRA_FIELDS:
        if field not in fieldnames:
            fieldnames.append(field)
    verify_rows(rows, resolver=resolver)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=output_path.name + ".", suffix=".tmp", dir=output_path.parent)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary_name, output_path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return Counter(row["verificatiestatus"] for row in rows)


def main():
    input_path = sys.argv[1] if len(sys.argv) > 1 else "perslijst.csv"
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    try:
        counts = verify_file(input_path, output_path)
    except (OSError, ValueError) as error:
        print(f"Kan niet verifiëren: {error}", file=sys.stderr)
        return 2
    print("Verificatie: " + ", ".join(f"{name}: {count}" for name, count in sorted(counts.items())), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
