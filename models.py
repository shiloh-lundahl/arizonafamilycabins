from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class Page(db.Model):
    __tablename__ = "pages"

    id = db.Column(db.Integer, primary_key=True)
    page_type = db.Column(db.String(20), nullable=False)  # location | type | situation | property
    url_slug = db.Column(db.String(200), unique=True, nullable=False)
    meta_title = db.Column(db.String(80))
    meta_description = db.Column(db.String(160))
    h1_title = db.Column(db.Text)
    hero_text = db.Column(db.Text)
    why_section = db.Column(db.Text)
    how_section = db.Column(db.Text)
    local_section = db.Column(db.Text)
    faq_section = db.Column(db.JSON)
    schema_markup = db.Column(db.JSON)
    internal_links = db.Column(db.JSON)
    target_keyword = db.Column(db.String(200))
    is_published = db.Column(db.Boolean, default=True)
    noindex = db.Column(db.Boolean, default=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Article(db.Model):
    __tablename__ = "articles"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(200), unique=True, nullable=False)
    h1 = db.Column(db.Text)
    meta_title = db.Column(db.String(80))
    meta_description = db.Column(db.String(160))
    target_keyword = db.Column(db.String(200))
    body_markdown = db.Column(db.Text)
    body_html = db.Column(db.Text)
    faq_section = db.Column(db.JSON)
    schema_markup = db.Column(db.JSON)
    is_published = db.Column(db.Boolean, default=True)
    published_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Lead(db.Model):
    __tablename__ = "leads"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200))
    email = db.Column(db.String(200))
    phone = db.Column(db.String(50))
    message = db.Column(db.Text)
    cabin_interest = db.Column(db.String(100))
    group_size = db.Column(db.String(50))
    check_in = db.Column(db.String(50))
    check_out = db.Column(db.String(50))
    source_page = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    hubspot_synced = db.Column(db.Boolean, default=False)
