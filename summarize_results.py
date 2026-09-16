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
    media_with_contacts = {row["medium"] for row in contacts}
    limburg = [row for row in contacts if "limburg" in row["regio"].lower() or row["prioriteit"] == "hoog"]
    press_relevant = [row for row in contacts if int(row["score"]) >= 65]
    cross_domain = [row for row in contacts if row.get("email_domeincontrole") == "ander_domein_controleren"]
    lines = [
        f"Publieke contactadressen: {len(contacts)}",
        f"Persrelevante adressen met score 65 of hoger: {len(press_relevant)}",
        f"Media in catalogus: {len(reports)}",
        f"Media met minstens één adres: {len(media_with_contacts)}",
        f"Limburg en hoge prioriteit: {len(limburg)} adressen",
        f"Adressen op een ander domein, handmatig controleren: {len(cross_domain)}",
        "",
        "Contactsoorten:",
    ]
    lines.extend(f"- {name}: {count}" for name, count in Counter(row["type"] for row in contacts).most_common())
    lines.extend(["", "Categorieën:"])
    lines.extend(f"- {name or 'niet ingevuld'}: {count}" for name, count in Counter(row["categorie"] for row in contacts).most_common())
    lines.extend(["", "Status per medium:"])
    lines.extend(f"- {name}: {count}" for name, count in Counter(row["status"] for row in reports).most_common())
    Path(output_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(lines[0] + "; " + lines[1] + "; " + lines[2] + "; " + lines[3], flush=True)


if __name__ == "__main__":
    main()
