"""
Load all JSON page files and markdown articles into the database.
Run locally: python scripts/load_content.py
On Render free: use the /admin/load-content-XK9mP2vQ7/ route instead.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import glob, json
from datetime import datetime
import markdown as md
from app import app
from models import db, Page, Article

with app.app_context():
    db.create_all()
    pages_loaded = 0
    articles_loaded = 0

    for filepath in sorted(glob.glob("content/pages/*.json")):
        with open(filepath) as f:
            data = json.load(f)
        slug = data["url_slug"]
        page = Page.query.filter_by(url_slug=slug).first()
        if not page:
            page = Page(url_slug=slug)
            db.session.add(page)
        for key, val in data.items():
            if hasattr(page, key):
                setattr(page, key, val)
        page.updated_at = datetime.utcnow()
        pages_loaded += 1
        print(f"  ✓ page: /{slug}/")

    for filepath in sorted(glob.glob("content/articles/*.md")):
        with open(filepath) as f:
            raw = f.read()
        meta = {}
        body = raw
        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) >= 3:
                for line in parts[1].strip().splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        meta[k.strip()] = v.strip()
                body = parts[2].strip()
        slug = meta.get("slug", "")
        if not slug:
            continue
        article = Article.query.filter_by(slug=slug).first()
        if not article:
            article = Article(slug=slug)
            db.session.add(article)
        article.h1 = meta.get("h1", "")
        article.meta_title = meta.get("meta_title", "")[:80]
        article.meta_description = meta.get("meta_description", "")[:160]
        article.target_keyword = meta.get("target_keyword", "")
        article.body_markdown = body
        article.body_html = md.markdown(body, extensions=["extra", "toc"])
        article.is_published = meta.get("is_published", "true").lower() == "true"
        article.updated_at = datetime.utcnow()
        articles_loaded += 1
        print(f"  ✓ article: /blog/{slug}/")

    db.session.commit()
    print(f"\nDone: {pages_loaded} pages, {articles_loaded} articles loaded.")
