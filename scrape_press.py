import csv
import re
import sys
import time
from collections import deque
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
CONTACT_WORDS = (
    "contact", "redactie", "pers", "colofon", "over-ons", "over ons",
    "nieuwstip", "tip", "journalist", "editorial", "newsroom", "about"
)
IGNORE_PREFIXES = ("privacy@", "noreply@", "no-reply@", "webmaster@", "abuse@")

HEADERS = {
    "User-Agent": "PressListResearchBot/1.0 (+https://github.com/wowwouter/perslijst)"
}


def normalize_domain(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    parsed = urlparse(value)
    return parsed.netloc.lower().removeprefix("www.")


def same_domain(url: str, domain: str) -> bool:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return host == domain or host.endswith("." + domain)


def fetch(url: str):
    try:
        r = requests.get(url, headers=HEADERS, timeout=12, allow_redirects=True)
        ctype = r.headers.get("content-type", "")
        if r.ok and "text/html" in ctype:
            return r
    except requests.RequestException:
        pass
    return None


def classify(email: str, page_url: str, page_text: str) -> tuple[str, int]:
    e = email.lower()
    context = (page_url + " " + page_text[:5000]).lower()
    if e.startswith(IGNORE_PREFIXES):
        return "overslaan", 0
    score = 20
    kind = "algemeen"
    if any(x in e for x in ("redactie", "editor", "news", "nieuws")):
        kind, score = "redactie", 95
    elif any(x in e for x in ("pers", "press", "media")):
        kind, score = "pers", 90
    elif any(x in e for x in ("tip", "nieuwstip")):
        kind, score = "nieuwstip", 85
    elif any(x in e for x in ("info", "contact")):
        kind, score = "algemeen", 45

    if any(x in context for x in ("redactie", "journalist", "newsroom", "editorial")):
        score = min(100, score + 10)
    if any(x in context for x in ("klantenservice", "customer service", "advertentie", "adverteren")):
        score = max(5, score - 25)
    return kind, score


def discover_pages(base_url: str, domain: str, max_pages: int = 30):
    queue = deque([(base_url, 0)])
    seen = set()
    found = []

    while queue and len(seen) < max_pages:
        url, depth = queue.popleft()
        if url in seen or depth > 2:
            continue
        seen.add(url)
        r = fetch(url)
        if not r:
            continue

        soup = BeautifulSoup(r.text, "lxml")
        text = soup.get_text(" ", strip=True)
        found.append((r.url, soup, text))

        for a in soup.find_all("a", href=True):
            href = urljoin(r.url, a["href"]).split("#", 1)[0]
            label = (a.get_text(" ", strip=True) + " " + a["href"]).lower()
            if not same_domain(href, domain):
                continue
            if any(word in label for word in CONTACT_WORDS):
                queue.append((href, depth + 1))

        time.sleep(0.25)

    return found


def scrape_domain(domain: str):
    rows = []
    urls_to_try = [f"https://{domain}", f"https://www.{domain}"]
    pages = []
    for base in urls_to_try:
        pages = discover_pages(base, domain)
        if pages:
            break

    seen_emails = set()
    for page_url, soup, text in pages:
        candidates = set(EMAIL_RE.findall(text))
        for a in soup.select('a[href^="mailto:"]'):
            candidates.update(EMAIL_RE.findall(a.get("href", "")))

        for email in candidates:
            email = email.strip(".,;:()[]<>\"'").lower()
            if email in seen_emails:
                continue
            seen_emails.add(email)
            kind, score = classify(email, page_url, text)
            if score == 0:
                continue
            rows.append({
                "medium": domain,
                "domein": domain,
                "email": email,
                "type": kind,
                "score": score,
                "bron_url": page_url,
            })
    return rows


def main():
    input_path = sys.argv[1] if len(sys.argv) > 1 else "domains.txt"
    output_path = sys.argv[2] if len(sys.argv) > 2 else "perslijst.csv"

    with open(input_path, encoding="utf-8") as f:
        domains = [normalize_domain(line) for line in f if normalize_domain(line)]

    all_rows = []
    for i, domain in enumerate(domains, 1):
        print(f"[{i}/{len(domains)}] {domain}", flush=True)
        all_rows.extend(scrape_domain(domain))

    all_rows.sort(key=lambda r: (-r["score"], r["medium"], r["email"]))
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["medium", "domein", "email", "type", "score", "bron_url"])
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"Klaar: {len(all_rows)} adressen -> {output_path}")


if __name__ == "__main__":
    main()
