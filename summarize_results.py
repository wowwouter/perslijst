"""Create a short, human-readable summary next to the crawl CSV files."""

import csv
import sys
from collections import Counter
from pathlib import Path


def read(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main():
    contacts_path = sys.argv[1] if len(sys.argv) > 1 else "perslijst.csv"
    report_path = sys.argv[2] if len(sys.argv) > 2 else "perslijst_rapport.csv"
    output_path = sys.argv[3] if len(sys.argv) > 3 else "perslijst_samenvatting.txt"
    contacts = read(contacts_path)
    reports = read(report_path)
    unique_emails = {row["email"].lower() for row in contacts if row.get("email")}
    media_with_contacts = {row["medium"] for row in contacts}
    limburg = [row for row in contacts if row.get("provincie") == "Limburg"]
    press_relevant = [row for row in contacts if int(row["score"]) >= 65]
    source_confirmed = [row for row in contacts if row.get("bronverificatie") == "bevestigd_op_mediawebsite"]
    mail_route = [row for row in contacts if row.get("maildomein_status") in {"mx_aanwezig", "geen_mx_wel_adresrecord"}]
    mail_unknown = [row for row in contacts if row.get("maildomein_status") == "dns_controle_mislukt"]
    cross_domain = [row for row in contacts if row.get("email_domeincontrole", "").startswith("ander_domein")]
    lines = [
        f"Publieke medium-contactkoppelingen: {len(contacts)}",
        f"Unieke e-mailadressen: {len(unique_emails)}",
        f"Persrelevante adressen met score 65 of hoger: {len(press_relevant)}",
        f"Media in catalogus: {len(reports)}",
        f"Media met minstens één adres: {len(media_with_contacts)}",
        f"Limburg: {len(limburg)} adressen",
        f"Op de mediawebsite gepubliceerd: {len(source_confirmed)}",
        f"E-maildomein met mailroute: {len(mail_route)}",
        f"DNS-controle tijdelijk onbekend: {len(mail_unknown)}",
        f"Ander e-maildomein, maar op de mediawebsite gepubliceerd: {len(cross_domain)}",
        "",
        "Contactsoorten:",
    ]
    lines.extend(f"- {name}: {count}" for name, count in Counter(row["type"] for row in contacts).most_common())
    lines.extend(["", "Categorieën:"])
    lines.extend(f"- {name or 'niet ingevuld'}: {count}" for name, count in Counter(row["categorie"] for row in contacts).most_common())
    lines.extend(["", "Redactieonderwerpen:"])
    lines.extend(
        f"- {name or 'niet ingevuld'}: {count}"
        for name, count in Counter(row.get("redactie_onderwerp", "") for row in contacts).most_common()
    )
    lines.extend(["", "Status per medium:"])
    lines.extend(f"- {name}: {count}" for name, count in Counter(row["status"] for row in reports).most_common())
    Path(output_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(lines[0] + "; " + lines[1] + "; " + lines[2] + "; " + lines[3], flush=True)


if __name__ == "__main__":
    main()
