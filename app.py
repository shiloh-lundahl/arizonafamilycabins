import os
import json
import requests
from datetime import datetime
from flask import (Flask, render_template, request, redirect, url_for,
                   abort, Response, jsonify, make_response)
from models import db, Page, Article, Lead
from availability import get_availability, CABIN_ICAL_ENV
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

PHONE = os.environ.get("PHONE_NUMBER") or "(602) 430-2232"
PHONE_RAW = "".join(c for c in PHONE if c.isdigit())
SITE_URL = "https://arizonafamilycabins.com"
LEAD_NOTIFY_EMAIL = os.environ.get("LEAD_NOTIFY_EMAIL", "Shilohsassistant@gmail.com")

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

    _notify_lead_email(lead)
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


# ── Availability calendars ────────────────────────────────────────────────────

CABINS = {
    "parkway-lodge": {"name": "Parkway Lodge", "sleeps": 27},
    "mohave-cabin-treehouse": {"name": "Mohave Cabin with Treehouse", "sleeps": 33},
}


@app.route("/availability/")
def availability_page():
    return render_template("availability.html", cabins=CABINS)


@app.route("/api/availability/<slug>/")
def api_availability(slug):
    if slug not in CABIN_ICAL_ENV:
        abort(404)
    data = get_availability(slug)
    return jsonify(data)


# ── Blog ──────────────────────────────────────────────────────────────────────

# Blog categories — display name, short tagline, and longer intro for SEO
BLOG_CATEGORIES = {
    "things-to-do": {
        "name": "Things to Do Around Lakeside",
        "tagline": "Family fun and can't-miss attractions in Lakeside, Pinetop & Show Low.",
        "intro": "Beyond the trails and the fishing, there's a whole lot to do around the White Mountains — kayaking on Rainbow Lake, golf in Pinetop, the parks and shops in Show Low, scenic drives, seasonal events, and easy family outings everyone can enjoy.",
        "emoji": "🎉",
    },
    "places-to-eat": {
        "name": "Local Places to Eat",
        "tagline": "Where locals actually eat in Lakeside, Pinetop & Show Low.",
        "intro": "Some of the best meals in the White Mountains come from small, family-run spots you'd drive right past if you didn't know better. Here are the local restaurants, cafés, and bakeries worth planning a stop around.",
        "emoji": "🍽️",
    },
    "outdoor-adventures": {
        "name": "Outdoor Adventures",
        "tagline": "Hiking, fishing, lakes, and getting out into the pines.",
        "intro": "This is why people come to the White Mountains. Trout lakes, hundreds of miles of trail, cool mountain air, and enough forest to disappear into for a day. Here's how to make the most of the outdoors around Lakeside.",
        "emoji": "🏞️",
    },
    "trip-planning": {
        "name": "Trip Planning & Tips",
        "tagline": "Everything you need to plan the perfect White Mountains getaway.",
        "intro": "Practical, honest advice for planning your trip to Lakeside — when to come, how to get here, what to pack, and how to pull off a big family reunion without losing your mind.",
        "emoji": "🗺️",
    },
}


def _articles_by_category():
    """Return ordered list of (category_slug, meta, [articles]) with published posts."""
    out = []
    for slug, meta in BLOG_CATEGORIES.items():
        arts = Article.query.filter_by(is_published=True, category=slug).order_by(
            Article.order.asc(), Article.published_at.desc()
        ).all()
        if arts:
            out.append((slug, meta, arts))
    return out


@app.route("/blog/")
def blog_index():
    grouped = _articles_by_category()
    # any published posts with no/unknown category
    uncategorized = Article.query.filter_by(is_published=True).filter(
        (Article.category.is_(None)) | (~Article.category.in_(list(BLOG_CATEGORIES.keys())))
    ).order_by(Article.published_at.desc()).all()
    return render_template("blog_index.html", grouped=grouped,
                           categories=BLOG_CATEGORIES, uncategorized=uncategorized)


@app.route("/blog/category/<cat_slug>/")
def blog_category(cat_slug):
    meta = BLOG_CATEGORIES.get(cat_slug)
    if not meta:
        abort(404)
    articles = Article.query.filter_by(is_published=True, category=cat_slug).order_by(
        Article.order.asc(), Article.published_at.desc()
    ).all()
    return render_template("blog_category.html", cat_slug=cat_slug, meta=meta,
                           articles=articles, categories=BLOG_CATEGORIES)


@app.route("/blog/<slug>/")
def blog_post(slug):
    if slug == "category":
        abort(404)
    article = Article.query.filter_by(slug=slug, is_published=True).first_or_404()
    cat_meta = BLOG_CATEGORIES.get(article.category)
    # a few sibling posts in the same category for internal linking
    related = []
    if article.category:
        related = Article.query.filter_by(is_published=True, category=article.category).filter(
            Article.slug != slug).order_by(Article.order.asc()).limit(4).all()
    return render_template("blog_post.html", article=article, cat_meta=cat_meta,
                           related=related, categories=BLOG_CATEGORIES)


# ── Catch-all programmatic pages ─────────────────────────────────────────────

@app.route("/<slug>/")
def dynamic_page(slug):
    # protect named routes that Flask resolves before this
    protected = {"about", "how-to-book", "faq", "contact", "blog",
                 "parkway-lodge", "mohave-cabin-treehouse", "availability",
                 "api", "sitemap.xml", "robots.txt"}
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
    for slug in ["about", "how-to-book", "faq", "contact", "availability",
                 "parkway-lodge", "mohave-cabin-treehouse", "blog"]:
        add(f"{SITE_URL}/{slug}/")

    for page in Page.query.filter_by(is_published=True, noindex=False).all():
        ts = page.updated_at.strftime("%Y-%m-%d") if page.updated_at else None
        add(f"{SITE_URL}/{page.url_slug}/", ts)

    for cat_slug in BLOG_CATEGORIES:
        if Article.query.filter_by(is_published=True, category=cat_slug).first():
            add(f"{SITE_URL}/blog/category/{cat_slug}/")

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


# ── Email notification (forward every inquiry to the assistant) ───────────────
# Uses FormSubmit (no account, no API key, no password). On the FIRST submission
# it emails a one-time activation link to LEAD_NOTIFY_EMAIL — click it once and all
# future inquiries are delivered automatically.

def _notify_lead_email(lead: Lead):
    if not LEAD_NOTIFY_EMAIL:
        return
    cabin_labels = {
        "parkway_lodge": "Parkway Lodge (sleeps 27)",
        "mohave_cabin": "Mohave Cabin with Treehouse (sleeps 33)",
        "both": "Both cabins",
    }
    payload = {
        "_subject": f"New cabin inquiry — {lead.name or 'Website visitor'}",
        "_template": "table",
        "_replyto": lead.email or "",
        "Name": lead.name or "",
        "Phone": lead.phone or "",
        "Email": lead.email or "",
        "Cabin of interest": cabin_labels.get(lead.cabin_interest, lead.cabin_interest or "Not specified"),
        "Group size": lead.group_size or "",
        "Check-in": lead.check_in or "",
        "Check-out": lead.check_out or "",
        "Message": lead.message or "",
        "Came from": lead.source_page or "",
    }
    try:
        requests.post(
            f"https://formsubmit.co/ajax/{LEAD_NOTIFY_EMAIL}",
            json=payload,
            timeout=8,
            headers={"Accept": "application/json"},
        )
    except Exception:
        pass  # never block the guest on a notification hiccup


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


# ── Content loader (runs automatically on startup) ────────────────────────────
# Because the site can run on Render's free tier with an ephemeral SQLite DB,
# all content is (re)loaded from the committed JSON + markdown files on every boot.
# This means the website never depends on a persistent database to display pages.

def load_all_content():
    import glob
    import markdown as md

    base = os.path.dirname(__file__)
    db.create_all()
    pages_loaded = 0
    articles_loaded = 0

    # Load page JSON files
    for filepath in sorted(glob.glob(os.path.join(base, "content/pages/*.json"))):
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
    for filepath in sorted(glob.glob(os.path.join(base, "content/articles/*.md"))):
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
        article.category = meta.get("category", "") or None
        article.meta_title = meta.get("meta_title", "")[:80]
        article.meta_description = meta.get("meta_description", "")[:160]
        article.target_keyword = meta.get("target_keyword", "")
        try:
            article.order = int(meta.get("order", "100"))
        except ValueError:
            article.order = 100
        article.body_markdown = body
        article.body_html = md.markdown(body, extensions=["extra", "toc"])
        article.is_published = meta.get("is_published", "true").lower() == "true"
        article.updated_at = datetime.utcnow()
        articles_loaded += 1

    db.session.commit()
    return {"pages_loaded": pages_loaded, "articles_loaded": articles_loaded, "status": "ok"}


@app.route("/admin/reload-content/")
def admin_reload_content():
    return jsonify(load_all_content())


# ── Startup ───────────────────────────────────────────────────────────────────

with app.app_context():
    try:
        load_all_content()
    except Exception as e:
        # Don't crash the web server if content load hiccups; pages can be reloaded
        print(f"[startup] content load warning: {e}")

if __name__ == "__main__":
    app.run(debug=True)
