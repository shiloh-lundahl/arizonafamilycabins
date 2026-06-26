"""
SEO checker — run against local or live URL.
Usage: python scripts/check_seo.py http://localhost:5000
"""
import sys
import urllib.request
import urllib.error
from html.parser import HTMLParser

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:5000"

PATHS = [
    "/",
    "/parkway-lodge/",
    "/mohave-cabin-treehouse/",
    "/large-cabins-lakeside-arizona/",
    "/family-reunion-cabins-arizona/",
    "/sitemap.xml",
    "/robots.txt",
]


class SEOParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.h1_count = 0
        self.title = ""
        self.description = ""
        self.canonical = ""
        self.in_title = False
        self.has_faq_schema = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title":
            self.in_title = True
        if tag == "meta" and attrs.get("name") == "description":
            self.description = attrs.get("content", "")
        if tag == "link" and attrs.get("rel") == "canonical":
            self.canonical = attrs.get("href", "")
        if tag == "h1":
            self.h1_count += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if "FAQPage" in data:
            self.has_faq_schema = True


def check(path):
    url = BASE + path
    try:
        resp = urllib.request.urlopen(url, timeout=10)
        body = resp.read().decode("utf-8", errors="replace")
        status = resp.status
    except urllib.error.HTTPError as e:
        print(f"  ✗ {path} → HTTP {e.code}")
        return
    except Exception as e:
        print(f"  ✗ {path} → ERROR: {e}")
        return

    if path in ("/sitemap.xml", "/robots.txt"):
        ok = "<url>" in body if path == "/sitemap.xml" else "Sitemap:" in body
        mark = "✓" if ok else "✗"
        print(f"  {mark} {path} → {status} {'(valid)' if ok else '(INVALID)'}")
        return

    parser = SEOParser()
    parser.feed(body)

    issues = []
    if parser.h1_count != 1:
        issues.append(f"h1_count={parser.h1_count} (want 1)")
    if len(parser.title) > 60:
        issues.append(f"title too long ({len(parser.title)} chars)")
    if not parser.title:
        issues.append("missing title")
    if len(parser.description) > 155:
        issues.append(f"description too long ({len(parser.description)} chars)")
    if not parser.description:
        issues.append("missing meta description")
    if not parser.canonical:
        issues.append("missing canonical")
    elif not parser.canonical.startswith("https://arizonafamilycabins.com"):
        if BASE.startswith("http://localhost"):
            pass  # local dev canonical mismatch is expected
        else:
            issues.append(f"bad canonical: {parser.canonical}")
    wc = len(body.split())
    if wc < 400:
        issues.append(f"low word count ({wc})")

    mark = "✓" if not issues else "✗"
    detail = " | ".join(issues) if issues else f"title='{parser.title[:50]}' wc~{wc}"
    print(f"  {mark} {path} → {status} | {detail}")


print(f"\nSEO check against {BASE}\n{'─'*50}")
for p in PATHS:
    check(p)
print()
