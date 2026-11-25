import io
import os
import re
import secrets
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

import qrcode
from flask import (Flask, abort, flash, redirect, render_template, request,
                   send_file, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash


SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$|^[a-z0-9]$")


def create_app(test_config=None):
    app = Flask(__name__)
    data_dir = Path(os.environ.get("EVENT_DATA_DIR", "/data"))
    if test_config:
        data_dir = Path(test_config.get("DATA_DIR", data_dir))
    data_dir.mkdir(parents=True, exist_ok=True)
    secret_file = data_dir / ".secret"
    if secret_file.exists():
        secret = secret_file.read_text().strip()
    else:
        secret = secrets.token_hex(32)
        secret_file.write_text(secret)
        secret_file.chmod(0o600)
    app.secret_key = secret
    app.config.update(
        DATABASE=str(data_dir / "events.sqlite3"),
        ADMIN_PASSWORD=os.environ.get("EVENT_ADMIN_PASSWORD", "change-me-now"),
        PUBLIC_URL=os.environ.get("EVENT_PUBLIC_URL", "").rstrip("/"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)

    def db():
        connection = sqlite3.connect(app.config["DATABASE"])
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    with db() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL, subtitle TEXT NOT NULL DEFAULT '',
                date_text TEXT NOT NULL DEFAULT '', location TEXT NOT NULL DEFAULT '',
                accent TEXT NOT NULL DEFAULT '#8b1e3f', published INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                category TEXT NOT NULL DEFAULT 'Allgemein', name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '', price_cents INTEGER NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0, available INTEGER NOT NULL DEFAULT 1
            );
        """)

    def admin_required():
        if not session.get("admin"):
            abort(401)

    def valid_origin():
        origin = request.headers.get("Origin")
        if not origin:
            return True
        target = urlsplit(request.host_url)
        source = urlsplit(origin)
        return source.scheme == target.scheme and source.netloc == target.netloc

    @app.before_request
    def csrf_guard():
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not valid_origin():
            abort(403)

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self'; form-action 'self'; frame-ancestors 'none'"
        return response

    @app.get("/")
    def home():
        with db() as con:
            events = con.execute("SELECT * FROM events WHERE published=1 ORDER BY id DESC").fetchall()
        return render_template("home.html", events=events)

    @app.get("/e/<slug>")
    def event_page(slug):
        with db() as con:
            event = con.execute("SELECT * FROM events WHERE slug=? AND published=1", (slug,)).fetchone()
            if not event:
                abort(404)
            items = con.execute("SELECT * FROM items WHERE event_id=? AND available=1 ORDER BY category,sort_order,id", (event["id"],)).fetchall()
        groups = {}
        for item in items:
            groups.setdefault(item["category"], []).append(item)
        return render_template("event.html", event=event, groups=groups)

    @app.get("/e/<slug>/qr.png")
    def event_qr(slug):
        with db() as con:
            event = con.execute("SELECT slug FROM events WHERE slug=?", (slug,)).fetchone()
        if not event:
            abort(404)
        base = app.config["PUBLIC_URL"] or request.host_url.rstrip("/")
        image = qrcode.make(f"{base}{url_for('event_page', slug=slug)}")
        output = io.BytesIO()
        image.save(output, format="PNG")
        output.seek(0)
        return send_file(output, mimetype="image/png", download_name=f"qr-{slug}.png")

    @app.route("/admin/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            supplied = request.form.get("password", "")
            configured = app.config["ADMIN_PASSWORD"]
            valid = check_password_hash(configured, supplied) if configured.startswith(("scrypt:", "pbkdf2:")) else secrets.compare_digest(supplied, configured)
            if valid:
                session.clear()
                session["admin"] = True
                return redirect(url_for("admin"))
            flash("Passwort falsch.", "error")
        return render_template("login.html")

    @app.post("/admin/logout")
    def logout():
        session.clear()
        return redirect(url_for("home"))

    @app.get("/admin")
    def admin():
        admin_required()
        with db() as con:
            events = con.execute("SELECT e.*,COUNT(i.id) item_count FROM events e LEFT JOIN items i ON i.event_id=e.id GROUP BY e.id ORDER BY e.id DESC").fetchall()
        return render_template("admin.html", events=events)

    @app.post("/admin/events")
    def create_event():
        admin_required()
        slug = request.form.get("slug", "").strip().lower()
        title = request.form.get("title", "").strip()[:80]
        if not title or not SLUG_RE.fullmatch(slug):
            flash("Bitte Titel und eine gültige Adresse eingeben.", "error")
            return redirect(url_for("admin"))
        accent = request.form.get("accent", "#8b1e3f")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", accent):
            accent = "#8b1e3f"
        try:
            with db() as con:
                con.execute("INSERT INTO events(slug,title,subtitle,date_text,location,accent) VALUES(?,?,?,?,?,?)", (
                    slug, title, request.form.get("subtitle", "").strip()[:160],
                    request.form.get("date_text", "").strip()[:60], request.form.get("location", "").strip()[:100], accent))
        except sqlite3.IntegrityError:
            flash("Diese Adresse wird bereits verwendet.", "error")
        return redirect(url_for("admin"))

    @app.get("/admin/events/<int:event_id>")
    def edit_event(event_id):
        admin_required()
        with db() as con:
            event = con.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
            items = con.execute("SELECT * FROM items WHERE event_id=? ORDER BY category,sort_order,id", (event_id,)).fetchall()
        if not event:
            abort(404)
        return render_template("edit.html", event=event, items=items)

    @app.post("/admin/events/<int:event_id>/toggle")
    def toggle_event(event_id):
        admin_required()
        with db() as con:
            con.execute("UPDATE events SET published=1-published WHERE id=?", (event_id,))
        return redirect(url_for("edit_event", event_id=event_id))

    @app.post("/admin/events/<int:event_id>/items")
    def add_item(event_id):
        admin_required()
        name = request.form.get("name", "").strip()[:100]
        raw_price = request.form.get("price", "").strip().replace(",", ".")
        try:
            cents = int((Decimal(raw_price) * 100).quantize(Decimal("1")))
            if cents < 0 or cents > 10_000_000:
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            flash("Bitte einen gültigen Preis eingeben.", "error")
            return redirect(url_for("edit_event", event_id=event_id))
        if not name:
            flash("Der Artikel benötigt einen Namen.", "error")
            return redirect(url_for("edit_event", event_id=event_id))
        with db() as con:
            if not con.execute("SELECT 1 FROM events WHERE id=?", (event_id,)).fetchone():
                abort(404)
            con.execute("INSERT INTO items(event_id,category,name,description,price_cents,sort_order) VALUES(?,?,?,?,?,?)", (
                event_id, request.form.get("category", "Allgemein").strip()[:60] or "Allgemein", name,
                request.form.get("description", "").strip()[:180], cents, int(request.form.get("sort_order", 0) or 0)))
        return redirect(url_for("edit_event", event_id=event_id))

    @app.post("/admin/events/<int:event_id>/items/<int:item_id>/delete")
    def delete_item(event_id, item_id):
        admin_required()
        with db() as con:
            con.execute("DELETE FROM items WHERE id=? AND event_id=?", (item_id, event_id))
        return redirect(url_for("edit_event", event_id=event_id))

    @app.get("/health")
    def health():
        return {"ok": True, "version": "0.1.0"}

    return app
