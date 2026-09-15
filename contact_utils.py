"""Extract explicitly published contacts; keep extraction separate from crawling."""

import json
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Comment

EMAIL_RE = re.compile(r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,63}", re.I)
OBFUSCATED_RE = re.compile(
    r"([\w.+-]+)\s*(?:\[at\]|\(at\))\s*([\w.-]+)"
    r"\s*(?:\[dot\]|\(dot\))\s*([a-z]{2,63})", re.I
)
CONTACT_RE = re.compile(
    r"\b(?:contact\w*|redactie\w*|colofon|nieuwstip\w*|tip|tips|pers|press|"
    r"journalist\w*|editorial|newsroom|over[\s_-]ons|about(?:[\s_-]us)?)\b", re.I
)
ASSET_SUFFIXES = (".jpg", ".jpeg", ".png", ".svg", ".gif", ".webp", ".css", ".js", ".pdf", ".zip", ".mp4")
TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


def canonical_url(value: str, base: str = "") -> str:
    """Remove fragments/tracking only; preserve query values that change content."""
    try:
        parsed = urlsplit(urljoin(base, value.strip()))
        if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
            return ""
        if parsed.username or parsed.password:
            return ""
        host = parsed.hostname.encode("idna").decode("ascii").lower()
        port = parsed.port
        if ":" in host:
            return ""
        netloc = host if port in (None, 80 if parsed.scheme == "http" else 443) else f"{host}:{port}"
        query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
                 if not k.lower().startswith("utm_") and k.lower() not in TRACKING_KEYS]
        return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", urlencode(sorted(query)), ""))
    except (ValueError, UnicodeError):
        return ""


def normalize_domain(value: str) -> str:
    url = canonical_url(value if "://" in value else "https://" + value)
    return (urlsplit(url).hostname or "").removeprefix("www.")


def same_domain(url: str, domain: str) -> bool:
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    return host == domain or host.endswith("." + domain)


def contact_links(soup: BeautifulSoup, base: str, domain: str):
    links = {}
    for anchor in soup.find_all("a", href=True):
        url = canonical_url(anchor["href"], base)
        if not url or not same_domain(url, domain) or urlsplit(url).path.lower().endswith(ASSET_SUFFIXES):
            continue
        label = anchor.get_text(" ", strip=True) + " " + unquote(urlsplit(url).path)
        if not CONTACT_RE.search(label):
            continue
        priority = 100 if re.search(r"\b(?:contact\w*|redactie\w*|colofon|newsroom)\b", label, re.I) else 50
        links[url] = max(links.get(url, 0), priority)
    return sorted(links.items(), key=lambda item: (-item[1], item[0]))


@dataclass(frozen=True)
class Contact:
    email: str
    method: str
    context: str


def valid_email(value: str) -> str:
    value = value.strip(".,;:()[]<>\"' ").lower()
    if not EMAIL_RE.fullmatch(value) or len(value) > 254:
        return ""
    local, domain = value.rsplit("@", 1)
    if len(local) > 64 or local.startswith(".") or local.endswith(".") or ".." in value:
        return ""
    if domain.endswith(ASSET_SUFFIXES) or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", part) for part in domain.split(".")):
        return ""
    return value


def text_contacts(text: str, method: str):
    for match in EMAIL_RE.finditer(text):
        email = valid_email(match.group())
        if email:
            yield Contact(email, method, text[max(0, match.start() - 150):match.end() + 150])
    for match in OBFUSCATED_RE.finditer(text):
        email = valid_email(f"{match[1]}@{match[2]}.{match[3]}")
        if email:
            yield Contact(email, "tekst_at_dot", text[max(0, match.start() - 150):match.end() + 150])


def json_contacts(value):
    if isinstance(value, dict):
        context = " ".join(str(value.get(key, "")) for key in ("@type", "jobTitle", "contactType", "department"))
        for key, child in value.items():
            if key.lower() == "email":
                for raw in child if isinstance(child, list) else [child]:
                    if isinstance(raw, str):
                        for found in text_contacts(raw, "json_ld"):
                            yield Contact(found.email, found.method, context)
            elif isinstance(child, (dict, list)):
                yield from json_contacts(child)
    elif isinstance(value, list):
        for child in value:
            yield from json_contacts(child)


def extract_contacts(soup: BeautifulSoup):
    """Only visible text, mailto recipients and email fields in JSON-LD."""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            yield from json_contacts(json.loads(script.string or script.get_text()))
        except (ValueError, RecursionError):
            continue
    # Work on a copy: the crawler still needs the original page's links.
    visible = BeautifulSoup(str(soup), "lxml")
    for node in visible.select("script, style, template, head, svg, [hidden], [aria-hidden='true']"):
        node.decompose()
    for comment in visible.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    for anchor in visible.find_all("a", href=True):
        href = anchor["href"]
        if href.lower().startswith("mailto:"):
            # subject/body/cc query parameters are not contact addresses.
            recipients = unquote(href[7:].split("?", 1)[0])
            context = anchor.parent.get_text(" ", strip=True)
            if len(context) > 400:
                context = anchor.get_text(" ", strip=True)
            for found in text_contacts(recipients, "mailto"):
                yield Contact(found.email, found.method, context)
    for node in visible.find_all(string=True):
        parent_text = node.parent.get_text(" ", strip=True)
        for found in text_contacts(str(node), "tekst"):
            yield Contact(found.email, found.method, parent_text if len(parent_text) <= 400 else found.context)


def classify(email: str, context: str = "") -> tuple[str, int]:
    """These labels and scores are heuristics, not verified job titles."""
    local = email.split("@", 1)[0].lower()
    words = set(re.split(r"[._+-]", local))
    excluded = {"privacy", "noreply", "webmaster", "abuse", "sales", "jobs", "hr", "dpo", "support"}
    if words & excluded or local.startswith(("no-reply", "klantenservice", "customer", "advertentie", "adverteren", "vacature", "abonnement")):
        return "overslaan", 0
    if local.startswith(("redactie", "editorial", "newsdesk", "newsroom")) or words & {"nieuws", "news", "editor"}:
        return "redactie", 95
    if local.startswith(("nieuwstip", "tipderedactie")) or words & {"tip", "tips"}:
        return "nieuwstip", 90
    if local.startswith(("persvoorlichting", "perscontact")) or words & {"pers", "press", "media"}:
        return "pers", 85
    if re.search(r"\b(?:redactie\w*|journalist\w*|editor\w*|newsroom)\b", context, re.I):
        return "mogelijk_redactiecontact", 65
    if words & {"info", "contact"}:
        return "algemeen", 35
    return "te_beoordelen", 20
