"""Run with: python scrape_press.py domains.txt perslijst.csv"""

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

from contact_utils import canonical_url, classify, contact_links, extract_contacts, normalize_domain, same_domain

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
FIELDS = ["medium", "domein", "email", "type", "score", "bron_url", "bron_urls", "extractiemethode", "gevonden_op"]
REPORT_FIELDS = ["domein", "status", "paginas_gepland", "paginas_gelezen", "adressen", "meldingen", "controle_urls", "afsluiting"]


def read_targets(path):
    targets = {}
    for number, line in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
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
        domain = request.meta.get("media_domain") or spider.owner(original)
        if not domain or not same_domain(request.url, domain) or not canonical_url(request.url):
            raise IgnoreRequest("extern_domein")
        if domain in spider.stopped:
            raise IgnoreRequest("domein_gestopt")
        if request.url in spider.processed and not request.meta.get("dont_obey_robotstxt"):
            raise IgnoreRequest("dubbele_pagina")
        request.meta["download_slot"] = domain


class CautiousRobotsMiddleware(RobotsTxtMiddleware):
    """Do not interpret a failed robots download as permission to crawl."""

    def __init__(self, crawler):
        super().__init__(crawler)
        self.unavailable = set()
        self.delays = {}

    async def _parse_robots(self, response, netloc, request):
        domain = request.meta.get("media_domain")
        if response.status in (404, 410):
            response = response.replace(body=b"")
        elif response.status != 200 or b"<html" in response.body[:500].lower():
            self.unavailable.add(netloc)
            if domain:
                self.crawler.spider.note(domain, f"robots_http_{response.status}", response.url)
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
        self.targets = targets
        self.allowed_domains = list(targets)
        self.output = Path(output)
        self.max_pages = int(max_pages)
        self.max_depth = int(max_depth)
        self.scheduled = {domain: set() for domain in targets}
        self.processed = set()
        self.stopped = set()
        self.notes = {domain: Counter() for domain in targets}
        self.check_urls = {domain: set() for domain in targets}
        self.pages = Counter()
        self.rows = {}
        self.timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.output_saved = False

    def owner(self, url):
        return next((domain for domain in self.targets if same_domain(url, domain)), None)

    def note(self, domain, reason, url):
        self.notes[domain][reason] += 1
        self.check_urls[domain].add(url)

    def schedule(self, url, domain, depth, priority=0):
        url = canonical_url(url)
        if not url or not same_domain(url, domain) or url in self.scheduled[domain] or url in self.processed:
            return None
        if depth > self.max_depth or domain in self.stopped:
            return None
        if len(self.scheduled[domain]) >= self.max_pages:
            self.notes[domain]["paginalimiet"] = 1
            return None
        self.scheduled[domain].add(url)
        return scrapy.Request(url, callback=self.parse, errback=self.failed, priority=priority,
                              meta={"media_domain": domain, "crawl_depth": depth, "handle_httpstatus_list": list(range(400, 600))})

    async def start(self):
        for domain, urls in self.targets.items():
            for url in urls:
                request = self.schedule(url, domain, 0, 200)
                if request:
                    yield request

    def parse(self, response):
        domain = response.meta["media_domain"]
        depth = response.meta["crawl_depth"]
        if response.url in self.processed:
            return
        self.processed.add(response.url)
        if response.status != 200:
            self.note(domain, f"http_{response.status}", response.url)
            if response.status == 429:
                self.stopped.add(domain)
            return
        if not isinstance(response, HtmlResponse):
            self.note(domain, "geen_html", response.url)
            return
        soup = BeautifulSoup(response.text, "lxml")
        title = soup.title.get_text(" ", strip=True).lower() if soup.title else ""
        challenge = response.headers.get("cf-mitigated") == b"challenge" or title in {
            "just a moment...", "access denied", "attention required! | cloudflare", "verify you are human"
        }
        if challenge:
            self.note(domain, "mogelijke_botblokkade", response.url)
            self.stopped.add(domain)
            return
        self.pages[domain] += 1
        for contact in extract_contacts(soup):
            kind, score = classify(contact.email, contact.context)
            if score == 0:
                continue
            key = (domain, contact.email)
            row = {"medium": domain, "domein": domain, "email": contact.email, "type": kind,
                   "score": score, "bron_url": response.url, "bron_urls": {response.url},
                   "extractiemethode": contact.method, "gevonden_op": self.timestamp}
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
            if any(url not in self.scheduled[domain] and url not in self.processed for url, _ in links):
                self.notes[domain]["dieptelimiet"] = 1
            return
        for url, priority in links:
            request = self.schedule(url, domain, depth + 1, priority)
            if request:
                yield request

    def failed(self, failure):
        request = failure.request
        domain = request.meta["media_domain"]
        message = failure.getErrorMessage()
        if message in ("dubbele_pagina", "domein_gestopt"):
            return
        if "Forbidden by robots.txt" in message:
            reason = "robots_geblokkeerd"
        elif failure.check(IgnoreRequest):
            reason = message
        else:
            reason = "netwerk_" + failure.type.__name__
        self.note(domain, reason, request.url)
        if not failure.check(IgnoreRequest) and request.meta["crawl_depth"] == 0 and urlsplit(request.url).netloc == domain:
            request = self.schedule(f"https://www.{domain}{urlsplit(request.url).path}", domain, 0, 150)
            if request:
                yield request

    def closed(self, reason):
        rows = sorted(self.rows.values(), key=lambda row: (-row["score"], row["domein"], row["email"]))
        write_csv(self.output, FIELDS, ({**row, "bron_urls": " | ".join(sorted(row["bron_urls"]))} for row in rows))
        counts = Counter(row["domein"] for row in rows)
        reports = []
        for domain in self.targets:
            if reason != "finished":
                self.notes[domain]["crawl_onderbroken"] += 1
            if self.crawler.stats.get_value("spider_exceptions/count", 0):
                self.notes[domain]["interne_fout_in_run"] = 1
            status = "gevonden" if counts[domain] else "geen_adressen_gevonden"
            if not self.pages[domain]:
                status = "niet_uitgelezen"
            elif self.notes[domain]:
                status += "_onvolledig"
            reports.append({"domein": domain, "status": status, "paginas_gepland": len(self.scheduled[domain]),
                            "paginas_gelezen": self.pages[domain], "adressen": counts[domain],
                            "meldingen": " | ".join(f"{key}: {value}" for key, value in sorted(self.notes[domain].items())),
                            "controle_urls": " | ".join(sorted(self.check_urls[domain])), "afsluiting": reason})
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
    input_path = sys.argv[1] if len(sys.argv) > 1 else "domains.txt"
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
