"""Real HTTP and Scrapy integration tests against a temporary local website."""

import csv
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CrawlIntegrationTests(unittest.TestCase):
    def run_site(self, mode):
        hits = Counter()
        times = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                hits[self.path] += 1
                times.append((self.path, time.monotonic()))
                status, body, content_type, location = 200, '', 'text/html; charset=utf-8', None
                if self.path == '/robots.txt':
                    content_type = 'text/plain'
                    body = 'User-agent: *\nDisallow: /redactie/prive\n'
                    if mode == 'robots_error':
                        status = 503
                    elif mode == 'robots_redirect':
                        status, location = 302, f'http://localhost:{self.server.server_port}/robots-other.txt'
                    elif mode == 'robots_missing':
                        status, body = 404, 'Not found'
                    elif mode == 'crawl_delay':
                        body += 'Crawl-delay: 0.25\n'
                elif mode == 'cli':
                    body = '<p>redactie@krant.example</p>'
                elif mode == 'rate_limit':
                    status = 429
                elif mode == 'challenge':
                    body = '<title>Just a moment...</title><p>fake@krant.example</p>'
                elif self.path == '/':
                    if mode == 'robots_missing':
                        body = '<p>info@krant.example</p>'
                    else:
                        body = '''<a href="/contact">Contact</a><a href="/contact?utm_source=footer#mail">Contact</a>
                          <a href="/redactie/prive">Redactie</a><a href="/redactie/retry">Redactie</a>
                          <a href="/contact/redirect">Contact</a><a href="/sport/persoon">Persoon</a>'''
                elif self.path == '/contact':
                    body = '''<p><a href="mailto:redactie%40krant.example?body=ignored@example.org">Redactie</a></p>
                      <script type="application/ld+json">{"@type":"ContactPoint","email":"pers@krant.example"}</script>
                      <script>"tracker@analytics.example"</script><p>klantenservice@krant.example</p>'''
                elif self.path == '/redactie/retry':
                    if hits[self.path] == 1:
                        status = 503
                    else:
                        body = '<p>redactie@krant.example</p><p>Journalist jan@krant.example</p>'
                elif self.path == '/contact/redirect':
                    status, location = 302, f'http://localhost:{self.server.server_port}/external-contact'
                else:
                    status = 404
                data = body.encode()
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(data)))
                if location:
                    self.send_header('Location', location)
                self.end_headers()
                self.wfile.write(data)

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / 'result.csv'
                url = f'http://127.0.0.1:{server.server_port}/'
                # Same middleware/settings as production; only delays are shortened.
                script = f'''
from scrape_press import PressSpider, SETTINGS
from scrapy.crawler import CrawlerProcess
settings = dict(SETTINGS, DOWNLOAD_DELAY=0.01, AUTOTHROTTLE_ENABLED=False, RETRY_TIMES=1)
process = CrawlerProcess(settings)
crawler = process.create_crawler(PressSpider)
errors = []
process.crawl(crawler, targets={{'127.0.0.1': [{json.dumps(url)}]}}, output={json.dumps(str(output))}, max_pages=10).addErrback(errors.append)
process.start()
if errors or crawler.stats.get_value('spider_exceptions/count', 0):
    raise SystemExit(1)
'''
                command = [sys.executable, '-c', script]
                environment = dict(os.environ)
                if mode == 'cli':
                    input_path = Path(directory) / 'domains.txt'
                    input_path.write_text(url, encoding='utf-8')
                    command = [sys.executable, 'scrape_press.py', str(input_path), str(output)]
                    environment['PRESS_MAX_PAGES'] = '1'
                completed = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=40)
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                self.assertTrue(output.exists(), completed.stdout + completed.stderr)
                with output.open(encoding='utf-8-sig') as handle:
                    rows = list(csv.DictReader(handle))
                with output.with_name('result_rapport.csv').open(encoding='utf-8-sig') as handle:
                    report = next(csv.DictReader(handle))
                return hits, times, rows, report
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_complete_crawl_retries_scope_robots_and_provenance(self):
        hits, _, rows, report = self.run_site('normal')
        self.assertEqual({row['email'] for row in rows}, {'redactie@krant.example', 'pers@krant.example', 'jan@krant.example'})
        self.assertEqual(hits['/robots.txt'], 1)
        self.assertEqual(hits['/contact'], 1)
        self.assertEqual(hits['/redactie/retry'], 2)
        self.assertEqual(hits['/redactie/prive'], 0)
        self.assertEqual(hits['/external-contact'], 0)
        self.assertEqual(hits['/sport/persoon'], 0)
        self.assertIn('robots_geblokkeerd', report['meldingen'])
        self.assertIn('extern_domein', report['meldingen'])
        row = next(row for row in rows if row['email'].startswith('redactie@'))
        self.assertEqual(len(row['bron_urls'].split(' | ')), 2)

    def test_command_line_produces_both_outputs(self):
        _, _, rows, report = self.run_site('cli')
        self.assertEqual([row['email'] for row in rows], ['redactie@krant.example'])
        self.assertEqual(report['paginas_gelezen'], '1')
        self.assertIn('paginalimiet', report['meldingen'])

    def test_unavailable_robots_does_not_silently_allow_crawl(self):
        hits, _, rows, report = self.run_site('robots_error')
        self.assertEqual(hits['/robots.txt'], 2)
        self.assertEqual(hits['/'], 0)
        self.assertEqual(rows, [])
        self.assertEqual(report['status'], 'niet_uitgelezen')
        self.assertIn('robots_onbereikbaar', report['meldingen'])

    def test_external_robots_redirect_does_not_leave_medium(self):
        hits, _, _, report = self.run_site('robots_redirect')
        self.assertEqual(hits['/robots-other.txt'], 0)
        self.assertEqual(hits['/'], 0)
        self.assertIn('robots_onbereikbaar', report['meldingen'])

    def test_missing_robots_is_distinct_from_failure(self):
        hits, _, rows, _ = self.run_site('robots_missing')
        self.assertEqual(hits['/'], 1)
        self.assertIn('info@krant.example', [row['email'] for row in rows])

    def test_crawl_delay_is_observed(self):
        _, times, _, _ = self.run_site('crawl_delay')
        intervals = [later[1] - earlier[1] for earlier, later in zip(times, times[1:])]
        self.assertGreaterEqual(min(intervals), 0.23)

    def test_rate_limit_is_reported_without_retry(self):
        hits, _, rows, report = self.run_site('rate_limit')
        self.assertEqual(hits['/'], 1)
        self.assertEqual(rows, [])
        self.assertIn('http_429', report['meldingen'])

    def test_challenge_is_reported_without_collecting_fake_contacts(self):
        _, _, rows, report = self.run_site('challenge')
        self.assertEqual(rows, [])
        self.assertIn('mogelijke_botblokkade', report['meldingen'])


if __name__ == '__main__':
    unittest.main()
