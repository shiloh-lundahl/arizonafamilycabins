import os
import re
import json
import time
import threading
import requests
from datetime import datetime
from flask import (Flask, render_template, request, redirect, url_for,
                   abort, Response, jsonify, make_response)
from models import db, Page, Article, Lead, Subscriber
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
        "now_ts": int(time.time()),  # spam time-trap on the contact form
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


# ── Contact-form spam filtering ───────────────────────────────────────────────
# Layered scoring, NOT a single hard rule. Losing one real booking inquiry costs
# far more than receiving spam, so anything short of near-certain is still
# delivered — just flagged in the subject line so it can be filtered in Gmail.

SPAM_PHRASES = (
    "jackpot", "casino", "lottery", "crypto", "bitcoin", "forex", "viagra",
    "cialis", "payday", "loan offer", "make money", "work from home",
    "seo service", "seo expert", "backlink", "guest post", "web design service",
    "increase your traffic", "rank your", "digital marketing agency",
    "investment opportunity", "click here", "limited time offer", "act now",
    "congratulations you", "you have won", "claim your prize",
)

URL_RE = re.compile(r"(https?://|www\.|\.com/|\.ru\b|\.cn\b|\.top\b|\.xyz\b|bit\.ly|tinyurl)", re.I)


def _spam_score(name, email, phone, message, form_loaded_at):
    """Return (score, [reasons]). Higher = more likely spam."""
    score, why = 0, []
    msg = (message or "").lower()

    # Links in the message. Real guests asking about a cabin essentially never
    # paste URLs — this is the single strongest signal.
    if URL_RE.search(message or ""):
        score += 4
        why.append("link in message")

    hits = [p for p in SPAM_PHRASES if p in msg]
    if hits:
        score += 2 * len(hits)
        why.append(f"spam phrase: {', '.join(hits[:3])}")

    # Bots often submit instantly; humans take time to type.
    try:
        elapsed = time.time() - float(form_loaded_at)
        if 0 <= elapsed < 4:
            score += 3
            why.append(f"submitted in {elapsed:.1f}s")
    except (TypeError, ValueError):
        pass  # missing/garbled timestamp isn't itself suspicious

    # "Robertmindy" — two names jammed together, no space.
    n = (name or "").strip()
    if n and " " not in n and len(n) > 9:
        score += 1
        why.append("run-together name")

    # Phone with no US-plausible shape (guests here are ~97% domestic).
    digits = re.sub(r"\D", "", phone or "")
    if digits and not (10 <= len(digits) <= 11):
        score += 2
        why.append(f"implausible phone ({len(digits)} digits)")

    if msg and len(msg) > 1200:
        score += 1
        why.append("very long message")

    return score, why


@app.route("/contact/", methods=["POST"])
def contact_post():
    # Honeypot: hidden field humans never see. Accept silently so the bot thinks
    # it worked, but store and send nothing.
    if request.form.get("website", "").strip():
        print("[contact] honeypot tripped — dropped silently", flush=True)
        return redirect(url_for("contact_thanks"))

    score, why = _spam_score(
        request.form.get("name", ""),
        request.form.get("email", ""),
        request.form.get("phone", ""),
        request.form.get("message", ""),
        request.form.get("form_loaded_at"),
    )

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

    if score >= 6:
        # Near-certain spam. Log it (visible in Render logs if ever needed) but
        # don't email and don't pollute the CRM.
        print(f"[contact] BLOCKED as spam (score {score}: {'; '.join(why)}) "
              f"name={lead.name!r} email={lead.email!r}", flush=True)
        return redirect(url_for("contact_thanks"))

    if score >= 3:
        # Suspicious but not certain — still deliver, flagged, so a false
        # positive never costs a real booking.
        print(f"[contact] flagged possible spam (score {score}: {'; '.join(why)})", flush=True)
        _notify_lead_email(lead, spam_flag=f"score {score}: {'; '.join(why)}")
        return redirect(url_for("contact_thanks"))

    _notify_lead_email(lead)
    _push_to_hubspot(lead)

    return redirect(url_for("contact_thanks"))


@app.route("/contact/thanks/")
def contact_thanks():
    return render_template("contact_thanks.html")


# ── VIP email list ────────────────────────────────────────────────────────────

@app.route("/subscribe/", methods=["POST"])
def subscribe():
    # Honeypot: real users never fill a hidden field; bots fill everything.
    if request.form.get("website", "").strip():
        return _safe_redirect_back(subscribed=1)  # silently accept, don't store

    email = request.form.get("email", "").strip().lower()
    first_name = request.form.get("first_name", "").strip()

    if "@" not in email or "." not in email.split("@")[-1] or len(email) > 200:
        return _safe_redirect_back(error=1)

    # Local row is best-effort only — the DB is ephemeral on Render (see model docstring).
    try:
        existing = Subscriber.query.filter_by(email=email).first()
        if not existing:
            db.session.add(Subscriber(
                email=email,
                first_name=first_name,
                source_page=request.referrer or "",
            ))
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[vip-list] local save failed (non-fatal): {e}", flush=True)

    # HubSpot is the real store. Run in a thread so a slow API never stalls the redirect.
    threading.Thread(
        target=_subscribe_to_hubspot,
        args=(email, first_name, request.referrer or ""),
        daemon=True,
    ).start()

    return _safe_redirect_back(subscribed=1)


def _safe_redirect_back(**params):
    """Return the visitor to the page they signed up from, with a status flag.

    Only same-host referrers are honored — never redirect to an attacker-supplied
    external URL.
    """
    from urllib.parse import urlparse, urlencode

    ref = request.referrer or ""
    target = "/"
    if ref:
        p = urlparse(ref)
        if p.netloc == request.host and p.path:
            target = p.path
    return redirect(f"{target}?{urlencode(params)}#vip", 303)


def _subscribe_to_hubspot(email: str, first_name: str, source_page: str):
    """Create or update the contact in HubSpot as a newsletter subscriber.

    HubSpot returns 409 when the email already exists — that's a success for our
    purposes (they're already in the CRM), not an error.
    """
    api_key = os.environ.get("HUBSPOT_API_KEY")
    if not api_key:
        print("[vip-list] SKIPPED — HUBSPOT_API_KEY not set", flush=True)
        _notify_subscriber_fallback(email, first_name, "HUBSPOT_API_KEY not set")
        return

    props = {"email": email, "lifecyclestage": "subscriber"}
    if first_name:
        props["firstname"] = first_name

    try:
        resp = requests.post(
            "https://api.hubapi.com/crm/v3/objects/contacts",
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json={"properties": props},
            timeout=15,
        )
        if resp.status_code in (200, 201):
            print(f"[vip-list] HubSpot contact created: {email}", flush=True)
            return
        if resp.status_code == 409:
            print(f"[vip-list] already in HubSpot: {email}", flush=True)
            return
        print(f"[vip-list] HubSpot {resp.status_code}: {resp.text[:200]}", flush=True)
        _notify_subscriber_fallback(email, first_name, f"HubSpot {resp.status_code}")
    except Exception as e:
        print(f"[vip-list] HubSpot call FAILED: {e}", flush=True)
        _notify_subscriber_fallback(email, first_name, str(e))


def _notify_subscriber_fallback(email: str, first_name: str, reason: str):
    """If HubSpot didn't take the signup, email it so it is never lost.

    The local DB is wiped on restart, so without this a failed API call would
    silently drop a real subscriber.
    """
    if not (GMAIL_SMTP_USER and GMAIL_SMTP_APP_PASSWORD and LEAD_NOTIFY_EMAIL):
        return
    try:
        _send_gmail(
            LEAD_NOTIFY_EMAIL,
            "VIP list signup (needs manual add to HubSpot)",
            f"A visitor joined the VIP email list but HubSpot did not accept it.\n\n"
            f"Email: {email}\n"
            f"Name: {first_name or '(not provided)'}\n"
            f"Reason: {reason}\n\n"
            f"Please add them to HubSpot manually.\n",
        )
        print("[vip-list] fallback notification sent", flush=True)
    except Exception as e:
        print(f"[vip-list] fallback notification FAILED: {e}", flush=True)


# ── Property pages ────────────────────────────────────────────────────────────

@app.route("/parkway-lodge/")
def parkway_lodge():
    return render_template("property_parkway_lodge.html")


@app.route("/mohave-cabin-treehouse/")
def mohave_cabin():
    return render_template("property_mohave_cabin.html")


@app.route("/reviews/")
def reviews():
    return render_template("reviews.html")


# ── Availability calendars ────────────────────────────────────────────────────

CABINS = {
    "parkway-lodge": {"name": "Parkway Lodge", "sleeps": 27},
    "mohave-cabin-treehouse": {"name": "Mohave Cabin with a Treehouse", "sleeps": 33},
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
                 "parkway-lodge", "mohave-cabin-treehouse", "reviews", "availability",
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
                 "parkway-lodge", "mohave-cabin-treehouse", "reviews", "blog"]:
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
# Sends directly via Gmail SMTP using an app password — NOT FormSubmit.
# FormSubmit sits behind Cloudflare, which serves Render's server IP a JS bot
# challenge (HTTP 403 "Just a moment...") on every request — confirmed in
# production logs 2026-07-12. A server-to-server request can never solve that
# challenge, so FormSubmit is permanently unusable from this host. Do not
# revert to it.
#
# Requires two env vars (set in Render dashboard, never committed):
#   GMAIL_SMTP_USER          — the sending Gmail address (Shilohsassistant@gmail.com)
#   GMAIL_SMTP_APP_PASSWORD  — a 16-char Google "App Password" for that account
#                              (requires 2-Step Verification enabled first;
#                              generate at myaccount.google.com/apppasswords)
# If either is unset, sending is skipped (logged), so local/dev never breaks.

GMAIL_SMTP_USER = os.environ.get("GMAIL_SMTP_USER", "")
GMAIL_SMTP_APP_PASSWORD = os.environ.get("GMAIL_SMTP_APP_PASSWORD", "")


def _send_gmail(to_addr: str, subject: str, body: str):
    import smtplib
    import ssl
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = GMAIL_SMTP_USER
    msg["To"] = to_addr
    msg.set_content(body)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=20) as server:
        server.login(GMAIL_SMTP_USER, GMAIL_SMTP_APP_PASSWORD)
        server.send_message(msg)


def _send_lead_emails(lead_data: dict):
    # Runs in a background thread so a slow SMTP handshake never delays the
    # guest's redirect to the thank-you page.
    cabin_labels = {
        "parkway_lodge": "Parkway Lodge (sleeps 27)",
        "mohave_cabin": "Mohave Cabin with a Treehouse (sleeps 33)",
        "both": "Both cabins",
    }
    spam_flag = lead_data.get("spam_flag")
    notify_body = (
        (f"*** POSSIBLE SPAM — {spam_flag} ***\n"
         f"Delivered anyway in case it's genuine. Reply only if it looks real.\n\n"
         if spam_flag else "")
        + f"New inquiry from the website:\n\n"
        f"Name: {lead_data['name'] or '(not provided)'}\n"
        f"Phone: {lead_data['phone'] or '(not provided)'}\n"
        f"Email: {lead_data['email'] or '(not provided)'}\n"
        f"Cabin of interest: {cabin_labels.get(lead_data['cabin_interest'], lead_data['cabin_interest'] or 'Not specified')}\n"
        f"Group size: {lead_data['group_size'] or '(not provided)'}\n"
        f"Check-in: {lead_data['check_in'] or '(not provided)'}\n"
        f"Check-out: {lead_data['check_out'] or '(not provided)'}\n"
        f"Message: {lead_data['message'] or '(none)'}\n"
        f"Came from: {lead_data['source_page'] or ''}\n"
    )
    try:
        subject = (
            f"[Possible spam] Cabin inquiry — {lead_data['name'] or 'Website visitor'}"
            if spam_flag else
            f"New cabin inquiry — {lead_data['name'] or 'Website visitor'}"
        )
        _send_gmail(LEAD_NOTIFY_EMAIL, subject, notify_body)
        print("[lead-notify] notification email sent OK", flush=True)
    except Exception as e:
        print(f"[lead-notify] notification email FAILED: {e}", flush=True)

    if lead_data["email"]:
        autoresponse_body = (
            f"Hi {lead_data['name'] or 'there'},\n\n"
            "Thanks for reaching out to Arizona Family Cabins! This confirms we received "
            "your message and someone will get back to you shortly (usually within a few hours).\n\n"
            f"If it's urgent, call or text us directly at {PHONE}.\n\n"
            "Talk soon,\nArizona Family Cabins"
        )
        try:
            _send_gmail(
                lead_data["email"],
                "We got your message — Arizona Family Cabins",
                autoresponse_body,
            )
            print("[lead-notify] guest autoresponse sent OK", flush=True)
        except Exception as e:
            print(f"[lead-notify] guest autoresponse FAILED: {e}", flush=True)


def _notify_lead_email(lead: Lead, spam_flag: str = ""):
    if not LEAD_NOTIFY_EMAIL:
        return
    if not (GMAIL_SMTP_USER and GMAIL_SMTP_APP_PASSWORD):
        print("[lead-notify] SKIPPED — GMAIL_SMTP_USER/GMAIL_SMTP_APP_PASSWORD not set", flush=True)
        return
    lead_data = {
        "name": lead.name,
        "phone": lead.phone,
        "email": lead.email,
        "cabin_interest": lead.cabin_interest,
        "group_size": lead.group_size,
        "check_in": lead.check_in,
        "check_out": lead.check_out,
        "message": lead.message,
        "source_page": lead.source_page,
        "spam_flag": spam_flag,
    }
    threading.Thread(target=_send_lead_emails, args=(lead_data,), daemon=True).start()


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
