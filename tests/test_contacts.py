import csv
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import scrapy
from bs4 import BeautifulSoup
from scrapy.exceptions import IgnoreRequest
from scrapy.http import HtmlResponse

from contact_utils import (
    canonical_url, classify, contact_links, contact_matches_target, editorial_topic,
    extract_contacts, same_domain,
)
from scrape_press import PressSpider, ScopeMiddleware, read_targets, write_csv


class ContactTests(unittest.TestCase):
    def extract(self, html):
        return list(extract_contacts(BeautifulSoup(html, "lxml")))

    def test_mailto_decoding_and_no_body_or_cc_addresses(self):
        found = self.extract('<p>Redactie <a href="MAILTO:Redactie%40krant.example,tip%40krant.example?body=private@example.org&amp;cc=cc@example.org">Mail ons</a></p>')
        self.assertEqual({c.email for c in found}, {"redactie@krant.example", "tip@krant.example"})
        self.assertTrue(all(c.method == "mailto" for c in found))

    def test_structured_contacts_only_email_fields(self):
        found = self.extract('''<script type="application/ld+json">{"@graph":[
          {"@type":"ContactPoint","contactType":"redactie","email":"redactie@krant.example"},
          {"@type":"Person","jobTitle":"journalist","email":["jan@krant.example"]},
          {"articleBody":"Unrelated private@example.org"}]}</script>''')
        self.assertEqual({c.email for c in found}, {"redactie@krant.example", "jan@krant.example"})
        self.assertTrue(all(c.method == "json_ld" for c in found))
        jan = next(c for c in found if c.email.startswith("jan@"))
        self.assertEqual(classify(jan.email, jan.context)[0], "mogelijk_redactiecontact")

    def test_ignore_scripts_comments_attributes_and_image_names(self):
        found = self.extract('''<head><script>"tracker@analytics.example"</script></head>
          <style>logo@2x.png</style><!-- secret@example.org -->
          <p hidden>hidden@example.org</p><p data-email="attribute@example.org">Niets</p>
          <p>redactie@krant.example</p><script type="application/ld+json">{broken}</script>''')
        self.assertEqual({c.email for c in found}, {"redactie@krant.example"})

    def test_obfuscated_explicit_address(self):
        found = self.extract('<p>redactie [at] krant [dot] nl</p>')
        self.assertEqual([c.email for c in found], ["redactie@krant.nl"])
        self.assertEqual(found[0].method, "tekst_at_dot")

    def test_classification_uses_local_part_and_nearby_context(self):
        self.assertEqual(classify("info@nieuwsmedia.example"), ("algemeen", 35))
        self.assertEqual(classify("jaspers@press.example"), ("overslaan", 0))
        self.assertEqual(classify("redactie@krant.example", "Klantenservice in footer"), ("redactie", 95))
        self.assertEqual(classify("hr@krant.example")[1], 0)
        self.assertEqual(classify("klantenservice@krant.example", "redactie")[1], 0)

    def test_editorial_topic_and_shared_publisher_matching(self):
        self.assertEqual(editorial_topic("sport@krant.example", "", "algemeen nieuws", "deelredactie"), "sport")
        self.assertEqual(editorial_topic("redactie@haak.example", "", "haken en amigurumi", "redactie"), "haken en amigurumi")
        self.assertTrue(contact_matches_target(
            "marion@publisher.example", "Chief editor voor alle creatieve merken", "mogelijk_redactiecontact", "hobbyhandig"
        ))
        self.assertTrue(contact_matches_target(
            "monique@publisher.example", "Brand coordinator Aan de Haak", "mogelijk_redactiecontact", "aan de haak"
        ))
        self.assertFalse(contact_matches_target(
            "monique@publisher.example", "Brand coordinator Aan de Haak", "mogelijk_redactiecontact", "stitch & quilt"
        ))
        self.assertEqual(classify("danielle@publisher.example", "Finance & Office medewerker")[1], 0)

    def test_tracking_removed_and_meaningful_queries_preserved(self):
        self.assertEqual(canonical_url('/contact?utm_source=mail&desk=2#x', 'https://KRANT.example/'), 'https://krant.example/contact?desk=2')
        self.assertNotEqual(canonical_url('https://krant.example/contact?desk=1'), canonical_url('https://krant.example/contact?desk=2'))
        self.assertEqual(canonical_url('javascript:alert(1)'), '')
        self.assertFalse(same_domain('https://krant.example.evil.org', 'krant.example'))

    def test_contact_priorities_and_offtopic_links(self):
        soup = BeautifulSoup('''<a href="/sport/persoon">Een persoon</a><a href="/contact?utm_source=nav">Contact</a>
          <a href="https://offsite.example/contact">Contact</a><a href="/colofon.pdf">Colofon</a>
          <a href="/over-ons">Over ons</a><a href="/contact#footer">Mail</a>''', 'lxml')
        links = contact_links(soup, 'https://krant.example/', 'krant.example')
        self.assertEqual([url for url, _ in links], ['https://krant.example/contact', 'https://krant.example/over-ons'])

    def test_input_comments_dedup_and_explicit_contact_urls(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'domains.txt'
            path.write_text('\ufeff# Comment\nkrant.example\nkrant.example\nhttps://krant.example/contact\n', encoding='utf-8')
            self.assertEqual(read_targets(path), {'krant.example': ['https://krant.example/', 'https://krant.example/contact']})
            path.write_text('mailto:person@example.org')
            with self.assertRaises(ValueError):
                read_targets(path)

    def test_catalog_keeps_media_on_the_same_platform_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'media_catalog.csv'
            path.write_text(
                'id,medium,publicaties,seed_url,scope_domain,categorie,provincie,regio,stad,mediumthema,contact_trefwoorden,prioriteit,catalogusbron\n'
                'stad_a,Stad A,Stad A,https://platform.example/a/contact,platform.example,lokaal,Limburg,Parkstad,Heerlen,algemeen nieuws,stad a,hoog,https://source.example/\n'
                'stad_b,Stad B,Stad B,https://platform.example/b/contact,platform.example,lokaal,Utrecht,Eemland,Amersfoort,sport,stad b,normaal,https://source.example/\n',
                encoding='utf-8',
            )
            targets = read_targets(path)
            self.assertEqual(set(targets), {'stad_a', 'stad_b'})
            self.assertEqual(targets['stad_a']['medium'], 'Stad A')
            self.assertEqual(targets['stad_b']['urls'], ['https://platform.example/b/contact'])

    def test_csv_formula_neutralization(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'out.csv'
            write_csv(path, ['email'], [{'email': '=test@krant.example'}])
            with path.open(encoding='utf-8-sig') as handle:
                self.assertEqual(next(csv.DictReader(handle))['email'], "'=test@krant.example")


class CrawlUnitTests(unittest.TestCase):
    def setUp(self):
        self.spider = PressSpider(targets={'krant.example': ['https://krant.example/']}, output='unused.csv', max_pages=3)

    def response(self, url, html, depth=0):
        request = scrapy.Request(url, meta={'media_id': 'krant.example', 'scope_domain': 'krant.example', 'crawl_depth': depth})
        return HtmlResponse(url, body=html.encode(), encoding='utf-8', request=request)

    def test_budget_and_depth_are_bounded(self):
        self.assertIsNotNone(self.spider.schedule('https://krant.example/', 'krant.example', 0))
        self.assertIsNone(self.spider.schedule('https://krant.example/contact', 'krant.example', 3))
        self.spider.schedule('https://krant.example/contact', 'krant.example', 1)
        self.spider.schedule('https://krant.example/redactie', 'krant.example', 1)
        self.assertIsNone(self.spider.schedule('https://krant.example/colofon', 'krant.example', 1))
        self.assertEqual(self.spider.notes['krant.example']['paginalimiet'], 1)

    def test_duplicates_keep_best_context_and_all_sources(self):
        list(self.spider.parse(self.response('https://krant.example/contact', '<p>jan@krant.example</p>')))
        list(self.spider.parse(self.response('https://krant.example/redactie', '<p>Journalist <a href="mailto:jan@krant.example">Jan</a></p>')))
        self.assertEqual(len(self.spider.rows), 1)
        row = next(iter(self.spider.rows.values()))
        self.assertEqual(row['score'], 70)
        self.assertEqual(row['extractiemethode'], 'mailto')
        self.assertEqual(len(row['bron_urls']), 2)

    def test_redirect_scope_even_if_dont_filter_is_set(self):
        middleware = ScopeMiddleware.from_crawler(SimpleNamespace(spider=self.spider))
        request = scrapy.Request('https://other.example/contact', dont_filter=True,
                                 meta={'media_domain': 'krant.example', 'redirect_urls': ['https://krant.example/']})
        with self.assertRaisesRegex(IgnoreRequest, 'extern_domein'):
            middleware.process_request(request)

    def test_rate_limit_and_challenge_stop_medium(self):
        response = self.response('https://krant.example/contact', '').replace(status=429)
        list(self.spider.parse(response))
        self.assertIn('krant.example', self.spider.stopped_domains)
        self.assertIsNone(self.spider.schedule('https://krant.example/redactie', 'krant.example', 1))
        other = PressSpider(targets={'krant.example': []}, output='unused.csv')
        list(other.parse(self.response('https://krant.example/', '<title>Just a moment...</title>')))
        self.assertEqual(other.pages['krant.example'], 0)
        self.assertIn('mogelijke_botblokkade', other.notes['krant.example'])


if __name__ == '__main__':
    unittest.main()
