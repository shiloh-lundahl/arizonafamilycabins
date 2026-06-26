import os
import json
import requests
from datetime import datetime
from flask import (Flask, render_template, request, redirect, url_for,
                   abort, Response, jsonify, make_response)
from models import db, Page, Article, Lead
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")

database_url = os.environ.get("DATABASE_URL")
if database_url:
    # Render/Heroku ship postgres:// but SQLAlchemy 1.4+ needs postgresql://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
else:
    db_path = os.path.join(os.path.dirname(__file__), "local.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

PHONE = os.environ.get("PHONE_NUMBER", "(480) 555-0100")
PHONE_RAW = "".join(c for c in PHONE if c.isdigit())
SITE_URL = "https://arizonafamilycabins.com"

# ── Canonical-redirect middleware ────────────────────────────────────────────

@app.before_request
def canonical_redirect():
    host = request.host.lower()
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
    target = None

    # Only redirect www→non-www; only force https when behind Render's proxy
    forwarded_proto = request.headers.get("X-Forwarded-Proto")
    if host.startswith("www."):
        proto = forwarded_proto or "https"
        target = f"{proto}://{host[4:]}{request.full_path.rstrip('?')}"
    elif forwarded_proto and forwarded_proto != "https":
        target = f"https://{host}{request.full_path.rstrip('?')}"

    if target:
        return redirect(target, 301)

    path = request.path
    if not path.endswith("/") and "." not in path.split("/")[-1]:
        return redirect(path + "/", 308)


# ── Context processor ─────────────────────────────────────────────────────────

@app.context_processor
def inject_globals():
    return {
        "phone": PHONE,
        "phone_raw": PHONE_RAW,
        "site_url": SITE_URL,
        "current_year": datetime.utcnow().year,
    }


# ── Core routes ───────────────────────────────────────────────────────────────

@app.route("/")
def home():
    with app.app_context():
        db.create_all()
    return render_template("home.html")


@app.route("/about/")
def about():
    return render_template("about.html")


@app.route("/how-to-book/")
def how_to_book():
    return render_template("how_to_book.html")


@app.route("/faq/")
def faq():
    return render_template("faq.html")


@app.route("/contact/", methods=["GET"])
def contact():
    return render_template("contact.html")


@app.route("/contact/", methods=["POST"])
def contact_post():
    lead = Lead(
        name=request.form.get("name", "").strip(),
        email=request.form.get("email", "").strip(),
        phone=request.form.get("phone", "").strip(),
        message=request.form.get("message", "").strip(),
        cabin_interest=request.form.get("cabin_interest", "").strip(),
        group_size=request.form.get("group_size", "").strip(),
        check_in=request.form.get("check_in", "").strip(),
        check_out=request.form.get("check_out", "").strip(),
        source_page=request.referrer or "/contact/",
    )
    db.session.add(lead)
    db.session.commit()

    _push_to_hubspot(lead)

    return redirect(url_for("contact_thanks"))


@app.route("/contact/thanks/")
def contact_thanks():
    return render_template("contact_thanks.html")


# ── Property pages ────────────────────────────────────────────────────────────

@app.route("/parkway-lodge/")
def parkway_lodge():
    return render_template("property_parkway_lodge.html")


@app.route("/mohave-cabin-treehouse/")
def mohave_cabin():
    return render_template("property_mohave_cabin.html")


# ── Blog ──────────────────────────────────────────────────────────────────────

@app.route("/blog/")
def blog_index():
    articles = Article.query.filter_by(is_published=True).order_by(
        Article.published_at.desc()
    ).all()
    return render_template("blog_index.html", articles=articles)


@app.route("/blog/<slug>/")
def blog_post(slug):
    article = Article.query.filter_by(slug=slug, is_published=True).first_or_404()
    return render_template("blog_post.html", article=article)


# ── Catch-all programmatic pages ─────────────────────────────────────────────

@app.route("/<slug>/")
def dynamic_page(slug):
    # protect named routes that Flask resolves before this
    protected = {"about", "how-to-book", "faq", "contact", "blog",
                 "parkway-lodge", "mohave-cabin-treehouse",
                 "sitemap.xml", "robots.txt"}
    if slug in protected:
        abort(404)

    page = Page.query.filter_by(url_slug=slug, is_published=True).first_or_404()
    template_map = {
        "location": "page_location.html",
        "type": "page_type.html",
        "situation": "page_situation.html",
        "property": "page_type.html",
    }
    template = template_map.get(page.page_type, "page_location.html")
    return render_template(template, page=page)


# ── Sitemap ───────────────────────────────────────────────────────────────────

@app.route("/sitemap.xml")
def sitemap():
    seen = set()
    urls = []

    def add(loc, lastmod=None):
        if loc in seen:
            return
        seen.add(loc)
        urls.append({"loc": loc, "lastmod": lastmod or datetime.utcnow().strftime("%Y-%m-%d")})

    add(f"{SITE_URL}/")
    for slug in ["about", "how-to-book", "faq", "contact",
                 "parkway-lodge", "mohave-cabin-treehouse", "blog"]:
        add(f"{SITE_URL}/{slug}/")

    for page in Page.query.filter_by(is_published=True, noindex=False).all():
        ts = page.updated_at.strftime("%Y-%m-%d") if page.updated_at else None
        add(f"{SITE_URL}/{page.url_slug}/", ts)

    for article in Article.query.filter_by(is_published=True).all():
        ts = article.updated_at.strftime("%Y-%m-%d") if article.updated_at else None
        add(f"{SITE_URL}/blog/{article.slug}/", ts)

    xml = render_template("sitemap.xml", urls=urls)
    return Response(xml, mimetype="application/xml")


# ── Robots.txt ────────────────────────────────────────────────────────────────

@app.route("/robots.txt")
def robots():
    lines = [
        "User-agent: *",
        "Allow: /",
        f"Sitemap: {SITE_URL}/sitemap.xml",
    ]
    return Response("\n".join(lines), mimetype="text/plain")


# ── HubSpot integration ───────────────────────────────────────────────────────

def _push_to_hubspot(lead: Lead):
    api_key = os.environ.get("HUBSPOT_API_KEY")
    if not api_key:
        return
    try:
        payload = {
            "properties": {
                "firstname": lead.name.split()[0] if lead.name else "",
                "lastname": " ".join(lead.name.split()[1:]) if lead.name and len(lead.name.split()) > 1 else "",
                "email": lead.email,
                "phone": lead.phone,
                "message": lead.message,
                "hs_lead_status": "NEW",
            }
        }
        resp = requests.post(
            "https://api.hubapi.com/crm/v3/objects/contacts",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=5,
        )
        if resp.status_code in (200, 201):
            lead.hubspot_synced = True
            db.session.commit()
    except Exception:
        pass  # never block the user on CRM errors


# ── RUNONCE content loader (remove after first deploy) ─────────────────────────
# Trigger ONCE via: curl https://<your-service>.onrender.com/admin/load-content-XK9mP2vQ7/
# Then delete this route before going live.

@app.route("/admin/load-content-XK9mP2vQ7/")
def runonce_load_content():
    import glob
    import markdown as md

    db.create_all()
    pages_loaded = 0
    articles_loaded = 0

    # Load page JSON files
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

    # Load article markdown files
    for filepath in sorted(glob.glob("content/articles/*.md")):
        with open(filepath) as f:
            raw = f.read()
        # Parse simple frontmatter (--- key: value ---)
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

    db.session.commit()
    return jsonify({"pages_loaded": pages_loaded, "articles_loaded": articles_loaded, "status": "ok"})


# ── Startup ───────────────────────────────────────────────────────────────────

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True)
