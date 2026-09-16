"""Run with: python scrape_press.py media_catalog.csv perslijst.csv"""

import csv
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import scrapy
from bs4 import BeautifulSoup
from protego import Protego
from scrapy.crawler import CrawlerProcess
from scrapy.downloadermiddlewares.robotstxt import RobotsTxtMiddleware
from scrapy.exceptions import IgnoreRequest
from scrapy.http import HtmlResponse

from contact_utils import (\n    canonical_url, classify, contact_links, contact_matches_target, editorial_topic, extract_contacts,\n    normalize_domain, same_domain,\n)

BOT_NAME = "PressListResearchBot"
SETTINGS = {
    "USER_AGENT": f"{BOT_NAME}/2.0 (+https://github.com/wowwouter/perslijst)",
    "ROBOTSTXT_OBEY": True,
    "ROBOTSTXT_USER_AGENT": BOT_NAME,
    "CONCURRENT_REQUESTS": 4,
    "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
    "DOWNLOAD_DELAY": 1.0,
    "DOWNLOAD_DELAY_JITTER": 0,
    "AUTOTHROTTLE_ENABLED": True,
    "AUTOTHROTTLE_START_DELAY": 1.0,
    "AUTOTHROTTLE_MAX_DELAY": 30.0,
    "AUTOTHROTTLE_TARGET_CONCURRENCY": 0.5,
    "DOWNLOAD_TIMEOUT": 20,
    "DOWNLOAD_MAXSIZE": 4 * 1024 * 1024,
    "RETRY_TIMES": 2,
    "RETRY_HTTP_CODES": [408, 500, 502, 503, 504, 522, 524],
    "REDIRECT_MAX_TIMES": 5,
    "COOKIES_ENABLED": False,
    "TELNETCONSOLE_ENABLED": False,
    "LOG_LEVEL": "WARNING",
    "CLOSESPIDER_TIMEOUT": 1200,
    "DOWNLOADER_MIDDLEWARES": {
        "scrape_press.ScopeMiddleware": 40,
        "scrapy.downloadermiddlewares.offsite.OffsiteMiddleware": None,
        "scrapy.downloadermiddlewares.robotstxt.RobotsTxtMiddleware": None,
        "scrape_press.CautiousRobotsMiddleware": 100,
    },
}
FIELDS = [
    "medium", "publicaties", "categorie", "provincie", "regio", "stad", "mediumthema",
    "redactie_onderwerp", "prioriteit", "domein", "email", "email_domeincontrole", "type", "score",
    "bron_url", "bron_urls", "extractiemethode", "catalogusbron", "gevonden_op",
]
REPORT_FIELDS = [
    "medium", "publicaties", "categorie", "provincie", "regio", "stad", "mediumthema",
    "prioriteit", "domein", "status", "paginas_gepland", "paginas_gelezen", "adressen",
    "meldingen", "controle_urls", "afsluiting",
]
CATALOG_FIELDS = {
    "id", "medium", "publicaties", "seed_url", "scope_domain", "categorie", "provincie", "regio",
    "stad", "mediumthema", "contact_trefwoorden", "prioriteit", "catalogusbron",
}


def read_targets(path):
    path = Path(path)
    if path.suffix.lower() == ".csv":
        return read_catalog(path)
    targets = {}
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        url = canonical_url(line if "://" in line else "https://" + line)
        domain = normalize_domain(url)
        if not domain or "." not in domain or not re.fullmatch(r"[a-z0-9.-]+", domain):
            raise ValueError(f"Ongeldig domein of URL op regel {number}")
        if url not in targets.setdefault(domain, []):
            targets[domain].append(url)
    if not targets:
        raise ValueError("De domeinlijst bevat geen websites")
    return targets


def read_catalog(path):
    targets = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = CATALOG_FIELDS - set(reader.fieldnames or ())
        if missing:
            raise ValueError("Ontbrekende cataloguskolommen: " + ", ".join(sorted(missing)))
        for number, row in enumerate(reader, 2):
            media_id = row["id"].strip()
            medium = row["medium"].strip()
            raw_url = row["seed_url"].strip()
            url = canonical_url(raw_url if "://" in raw_url else "https://" + raw_url)
            scope = normalize_domain(row["scope_domain"].strip() or url)
            if not media_id or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", media_id):
                raise ValueError(f"Ongeldig id op regel {number}")
            if not medium or not url or not scope or "." not in scope or not same_domain(url, scope):
                raise ValueError(f"Ongeldige catalogusregel {number}")
            metadata = {
                "medium": medium,
                "publicaties": row["publicaties"].strip() or medium,
                "domain": scope,
                "categorie": row["categorie"].strip(),
                "provincie": row["provincie"].strip(),
                "regio": row["regio"].strip(),
                "stad": row["stad"].strip(),
                "mediumthema": row["mediumthema"].strip(),
                "contact_trefwoorden": row["contact_trefwoorden"].strip(),
                "prioriteit": row["prioriteit"].strip(),
                "catalogusbron": row["catalogusbron"].strip(),
                "urls": [],
            }
            previous = targets.setdefault(media_id, metadata)
            if {key: previous[key] for key in metadata if key != "urls"} != {
                key: metadata[key] for key in metadata if key != "urls"
            }:
                raise ValueError(f"Tegenstrijdige metadata voor id {media_id} op regel {number}")
            if url not in previous["urls"]:
                previous["urls"].append(url)
    if not targets:
        raise ValueError("De mediacatalogus bevat geen websites")
    return targets


def normalize_targets(targets):
    """Keep the old domain-list API usable for tests and simple local runs."""
    if all(isinstance(value, list) for value in targets.values()):
        return {
            domain: {
                "medium": domain, "publicaties": domain, "domain": domain, "categorie": "",
                "provincie": "", "regio": "", "stad": "", "mediumthema": "",
                "contact_trefwoorden": "", "prioriteit": "", "catalogusbron": "", "urls": urls,
            }
            for domain, urls in targets.items()
        }
    return targets


class ScopeMiddleware:
    """Check every redirect before requesting it, including robots redirects."""

    @classmethod
    def from_crawler(cls, crawler):
        instance = cls()
        instance.crawler = crawler
        return instance

    def process_request(self, request):
        spider = self.crawler.spider
        original = request.meta.get("redirect_urls", [request.url])[0]
        domain = request.meta.get("scope_domain") or spider.owner_domain(original)
        if not domain or not same_domain(request.url, domain) or not canonical_url(request.url):
            raise IgnoreRequest("extern_domein")
        if domain in spider.stopped_domains:
            raise IgnoreRequest("domein_gestopt")
        media_id = request.meta.get("media_id")
        if media_id and (media_id, request.url) in spider.processed and not request.meta.get("dont_obey_robotstxt"):
            raise IgnoreRequest("dubbele_pagina")
        request.meta["download_slot"] = domain


class CautiousRobotsMiddleware(RobotsTxtMiddleware):
    """Do not interpret a failed robots download as permission to crawl."""

    def __init__(self, crawler):
        super().__init__(crawler)
        self.unavailable = set()
        self.delays = {}

    async def _parse_robots(self, response, netloc, request):
        media_id = request.meta.get("media_id")
        if response.status in (404, 410):
            response = response.replace(body=b"")
        elif response.status != 200 or b"<html" in response.body[:500].lower():
            self.unavailable.add(netloc)
            if media_id:
                self.crawler.spider.note(media_id, f"robots_http_{response.status}", response.url)
        else:
            delay = Protego.parse(response.body.decode("utf-8", errors="replace")).crawl_delay(BOT_NAME)
            if delay is not None:
                self.delays[netloc] = float(delay)
        await super()._parse_robots(response, netloc, request)

    def _robots_error(self, exc, netloc):
        self.unavailable.add(netloc)
        super()._robots_error(exc, netloc)

    async def process_request(self, request):
        await super().process_request(request)
        if request.meta.get("dont_obey_robotstxt"):
            return
        netloc = urlsplit(request.url).netloc
        if netloc in self.unavailable:
            raise IgnoreRequest("robots_onbereikbaar")
        delay = self.delays.get(netloc, 0)
        if delay > self.crawler.settings.getfloat("AUTOTHROTTLE_MAX_DELAY"):
            raise IgnoreRequest("robots_crawl_delay_te_lang")
        if delay:
            slot = self.crawler.engine.downloader.slots.get(request.meta["download_slot"])
            if slot:
                slot.delay = max(slot.delay, delay)
                request.meta["autothrottle_dont_adjust_delay"] = True


class PressSpider(scrapy.Spider):
    name = "press_contacts"

    def __init__(self, targets, output, max_pages=30, max_depth=2, **kwargs):
        super().__init__(**kwargs)
        self.targets = normalize_targets(targets)
        self.allowed_domains = sorted({target["domain"] for target in self.targets.values()})
        self.output = Path(output)
        self.max_pages = int(max_pages)
        self.max_depth = int(max_depth)
        self.scheduled = {media_id: set() for media_id in self.targets}
        self.processed = set()
        self.stopped_domains = set()
        self.notes = {media_id: Counter() for media_id in self.targets}
        self.check_urls = {media_id: set() for media_id in self.targets}
        self.pages = Counter()
        self.rows = {}
        self.timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.output_saved = False

    def owner_domain(self, url):
        return next((target["domain"] for target in self.targets.values() if same_domain(url, target["domain"])), None)

    def note(self, media_id, reason, url):
        self.notes[media_id][reason] += 1
        self.check_urls[media_id].add(url)

    def schedule(self, url, media_id, depth, priority=0):
        domain = self.targets[media_id]["domain"]
        url = canonical_url(url)
        if not url or not same_domain(url, domain) or url in self.scheduled[media_id] or (media_id, url) in self.processed:
            return None
        if depth > self.max_depth or domain in self.stopped_domains:
            return None
        if len(self.scheduled[media_id]) >= self.max_pages:
            self.notes[media_id]["paginalimiet"] = 1
            return None
        self.scheduled[media_id].add(url)
        return scrapy.Request(url, callback=self.parse, errback=self.failed, priority=priority,
                              meta={"media_id": media_id, "scope_domain": domain, "crawl_depth": depth,
                                    "handle_httpstatus_list": list(range(400, 600))})

    async def start(self):
        ordered = sorted(self.targets.items(), key=lambda item: (item[1]["prioriteit"] != "hoog", item[1]["medium"]))
        for media_id, target in ordered:
            for url in target["urls"]:
                request = self.schedule(url, media_id, 0, 200)
                if request:
                    yield request

    def parse(self, response):
        media_id = response.meta["media_id"]
        target = self.targets[media_id]
        domain = target["domain"]
        depth = response.meta["crawl_depth"]
        if (media_id, response.url) in self.processed:
            return
        self.processed.add((media_id, response.url))
        if response.status != 200:
            self.note(media_id, f"http_{response.status}", response.url)
            if response.status == 429:
                self.stopped_domains.add(domain)
            return
        if not isinstance(response, HtmlResponse):
            self.note(media_id, "geen_html", response.url)
            return
        soup = BeautifulSoup(response.text, "lxml")
        title = soup.title.get_text(" ", strip=True).lower() if soup.title else ""
        challenge = response.headers.get("cf-mitigated") == b"challenge" or title in {
            "just a moment...", "access denied", "attention required! | cloudflare", "verify you are human"
        }
        if challenge:
            self.note(media_id, "mogelijke_botblokkade", response.url)
            self.stopped_domains.add(domain)
            return
        self.pages[media_id] += 1
        for contact in extract_contacts(soup):
            context = contact.context + " " + response.url
            kind, score = classify(contact.email, context)
            if score == 0 or not contact_matches_target(
                contact.email, context, kind, target["contact_trefwoorden"]
            ):
                continue
            key = (media_id, contact.email)
            email_domain = contact.email.rsplit("@", 1)[1]
            row = {
                "medium": target["medium"], "publicaties": target["publicaties"],
                "categorie": target["categorie"], "provincie": target["provincie"],
                "regio": target["regio"], "stad": target["stad"], "mediumthema": target["mediumthema"],
                "redactie_onderwerp": editorial_topic(
                    contact.email, context, target["mediumthema"], kind
                ),
                "prioriteit": target["prioriteit"], "domein": domain, "email": contact.email,
                "email_domeincontrole": "zelfde_domein" if same_domain("https://" + email_domain, domain)
                else "ander_domein_controleren", "type": kind,
                "score": score, "bron_url": response.url, "bron_urls": {response.url},
                "extractiemethode": contact.method, "catalogusbron": target["catalogusbron"],
                "gevonden_op": self.timestamp,
            }
            previous = self.rows.get(key)
            if previous:
                sources = previous["bron_urls"] | row["bron_urls"]
                rank = lambda item: (item["score"], item["extractiemethode"] in ("mailto", "json_ld"))
                if rank(previous) >= rank(row):
                    row = previous
                row["bron_urls"] = sources
            self.rows[key] = row
        links = contact_links(soup, response.url, domain)
        if depth == 0 and not links and urlsplit(response.url).path == "/":
            links = [(canonical_url(path, response.url), 10) for path in ("/contact", "/redactie", "/colofon")]
        if depth >= self.max_depth:
            if any(url not in self.scheduled[media_id] and (media_id, url) not in self.processed for url, _ in links):
                self.notes[media_id]["dieptelimiet"] = 1
            return
        for url, priority in links:
            request = self.schedule(url, media_id, depth + 1, priority)
            if request:
                yield request

    def failed(self, failure):
        request = failure.request
        media_id = request.meta["media_id"]
        domain = self.targets[media_id]["domain"]
        message = failure.getErrorMessage()
        if message in ("dubbele_pagina", "domein_gestopt"):
            return
        if "Forbidden by robots.txt" in message:
            reason = "robots_geblokkeerd"
        elif failure.check(IgnoreRequest):
            reason = message
        else:
            reason = "netwerk_" + failure.type.__name__
        self.note(media_id, reason, request.url)
        if not failure.check(IgnoreRequest) and request.meta["crawl_depth"] == 0 and urlsplit(request.url).netloc == domain:
            request = self.schedule(f"https://www.{domain}{urlsplit(request.url).path}", media_id, 0, 150)
            if request:
                yield request

    def closed(self, reason):
        rows = sorted(self.rows.values(), key=lambda row: (-row["score"], row["domein"], row["email"]))
        write_csv(self.output, FIELDS, ({**row, "bron_urls": " | ".join(sorted(row["bron_urls"]))} for row in rows))
        counts = Counter(media_id for media_id, _ in self.rows)
        reports = []
        for media_id, target in self.targets.items():
            if reason != "finished":
                self.notes[media_id]["crawl_onderbroken"] += 1
            if self.crawler.stats.get_value("spider_exceptions/count", 0):
                self.notes[media_id]["interne_fout_in_run"] = 1
            status = "gevonden" if counts[media_id] else "geen_adressen_gevonden"
            if not self.pages[media_id]:
                status = "niet_uitgelezen"
            elif self.notes[media_id]:
                status += "_onvolledig"
            reports.append({"medium": target["medium"], "publicaties": target["publicaties"],
                            "categorie": target["categorie"], "provincie": target["provincie"],
                            "regio": target["regio"], "stad": target["stad"],
                            "mediumthema": target["mediumthema"], "prioriteit": target["prioriteit"],
                            "domein": target["domain"], "status": status,
                            "paginas_gepland": len(self.scheduled[media_id]), "paginas_gelezen": self.pages[media_id],
                            "adressen": counts[media_id],
                            "meldingen": " | ".join(f"{key}: {value}" for key, value in sorted(self.notes[media_id].items())),
                            "controle_urls": " | ".join(sorted(self.check_urls[media_id])), "afsluiting": reason})
        write_csv(self.output.with_name(self.output.stem + "_rapport.csv"), REPORT_FIELDS, reports)
        self.output_saved = True
        print(f"Klaar: {len(rows)} adressen, {sum(self.pages.values())} pagina's gelezen. Zie ook het rapport.", flush=True)


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            safe = {key: "'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value
                    for key, value in row.items()}
            writer.writerow(safe)


def main():
    input_path = sys.argv[1] if len(sys.argv) > 1 else "media_catalog.csv"
    output_path = sys.argv[2] if len(sys.argv) > 2 else "perslijst.csv"
    try:
        targets = read_targets(input_path)
        max_pages = int(os.environ.get("PRESS_MAX_PAGES", "30"))
        if not 1 <= max_pages <= 100:
            raise ValueError("Het maximum moet tussen 1 en 100 pagina's liggen")
    except (OSError, ValueError) as error:
        print(f"Kan niet starten: {error}", file=sys.stderr)
        return 2
    process = CrawlerProcess(SETTINGS)
    crawler = process.create_crawler(PressSpider)
    errors = []
    process.crawl(crawler, targets=targets, output=output_path, max_pages=max_pages).addErrback(errors.append)
    process.start()
    if errors or crawler.stats.get_value("spider_exceptions/count", 0) or not crawler.spider.output_saved:
        print("De run bevat een interne fout; controleer de logs.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
