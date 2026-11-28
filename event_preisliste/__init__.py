import io
import csv
import json
import os
import re
import secrets
import shutil
import sqlite3
import tempfile
import time
import zipfile
from collections import defaultdict, deque
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

import qrcode
from PIL import Image, UnidentifiedImageError
from flask import (Flask, abort, flash, jsonify, redirect, render_template, request,
                   Response, send_file, send_from_directory, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from flask.sessions import SecureCookieSessionInterface


SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$|^[a-z0-9]$")
APP_VERSION = "0.9.1"


class ProxyAwareSessionCookies(SecureCookieSessionInterface):
    def get_cookie_secure(self, app):
        return (
            super().get_cookie_secure(app)
            or request.is_secure
            or request.headers.get("X-Forwarded-Proto", "").split(",")[-1].strip() == "https"
        )


def create_app(test_config=None):
    app = Flask(__name__)
    app.session_interface = ProxyAwareSessionCookies()
    data_dir = Path(os.environ.get("EVENT_DATA_DIR", "/data"))
    if test_config:
        data_dir = Path(test_config.get("DATA_DIR", data_dir))
    data_dir.mkdir(parents=True, exist_ok=True)
    map_dir = data_dir / "maps"
    map_dir.mkdir(exist_ok=True)
    stand_dir = data_dir / "stands"
    stand_dir.mkdir(exist_ok=True)
    backup_dir = data_dir / "backups"
    backup_dir.mkdir(exist_ok=True)
    secret_file = data_dir / ".secret"
    if secret_file.exists():
        secret = secret_file.read_text().strip()
    else:
        secret = secrets.token_hex(32)
        secret_file.write_text(secret)
    secret_file.chmod(0o600)
    password_file = data_dir / ".initial-admin-password"
    password_hash_file = data_dir / ".admin-password-hash"
    admin_password = os.environ.get("EVENT_ADMIN_PASSWORD", "").strip()
    needs_setup = False
    if password_hash_file.exists():
        admin_password = password_hash_file.read_text().strip()
    elif not admin_password and password_file.exists():
        # Backwards compatibility for installations created before v0.5.1.
        admin_password = password_file.read_text().strip()
    elif not admin_password and test_config and test_config.get("ADMIN_PASSWORD"):
        admin_password = test_config["ADMIN_PASSWORD"]
    elif not admin_password:
        needs_setup = True
    app.secret_key = secret
    app.config.update(
        DATABASE=str(data_dir / "events.sqlite3"),
        ADMIN_PASSWORD=admin_password,
        NEEDS_SETUP=needs_setup,
        PUBLIC_URL=os.environ.get("EVENT_PUBLIC_URL", "").rstrip("/"),
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_REFRESH_EACH_REQUEST=False,
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)
    public_url = urlsplit(app.config["PUBLIC_URL"])
    if app.config["PUBLIC_URL"] and (
        public_url.scheme not in {"http", "https"}
        or not public_url.hostname
        or public_url.username
        or public_url.password
        or public_url.path not in {"", "/"}
        or public_url.query
        or public_url.fragment
    ):
        raise ValueError("EVENT_PUBLIC_URL must be an HTTP(S) origin without a path.")
    login_attempts = defaultdict(deque)

    @app.context_processor
    def app_metadata():
        return {"app_version": APP_VERSION}

    def refresh_password_state():
        """Synchronize first-run setup across all Gunicorn workers."""
        if app.config["NEEDS_SETUP"] and password_hash_file.exists():
            app.config["ADMIN_PASSWORD"] = password_hash_file.read_text().strip()
            app.config["NEEDS_SETUP"] = False

    def write_admin_hash(hashed):
        temporary = data_dir / f".admin-password-{secrets.token_hex(6)}.tmp"
        temporary.write_text(hashed)
        temporary.chmod(0o600)
        os.replace(temporary, password_hash_file)

    def db():
        connection = sqlite3.connect(app.config["DATABASE"])
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def selected_stand_id(connection, event_id):
        try:
            stand_id = int(request.form.get("stand_id", "") or 0)
        except ValueError:
            return None
        if stand_id and connection.execute("SELECT 1 FROM stands WHERE id=? AND event_id=?", (stand_id, event_id)).fetchone():
            return stand_id
        return None

    def form_int(name, default=0, minimum=-10000, maximum=10000):
        try:
            return max(minimum, min(maximum, int(request.form.get(name, default) or default)))
        except (TypeError, ValueError):
            return default

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
            CREATE TABLE IF NOT EXISTS stands (
                id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
                kind TEXT NOT NULL DEFAULT 'stand', accent TEXT NOT NULL DEFAULT '#1f6f5c',
                sort_order INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS map_markers (
                id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                label TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'stand',
                x_percent REAL NOT NULL, y_percent REAL NOT NULL
            );
        """)
        columns = {row["name"] for row in con.execute("PRAGMA table_info(events)")}
        if "map_filename" not in columns:
            con.execute("ALTER TABLE events ADD COLUMN map_filename TEXT NOT NULL DEFAULT ''")
        if "opening_hours" not in columns:
            con.execute("ALTER TABLE events ADD COLUMN opening_hours TEXT NOT NULL DEFAULT ''")
        if "publish_from" not in columns:
            con.execute("ALTER TABLE events ADD COLUMN publish_from TEXT NOT NULL DEFAULT ''")
        if "publish_until" not in columns:
            con.execute("ALTER TABLE events ADD COLUMN publish_until TEXT NOT NULL DEFAULT ''")
        item_columns = {row["name"] for row in con.execute("PRAGMA table_info(items)")}
        if "labels" not in item_columns:
            con.execute("ALTER TABLE items ADD COLUMN labels TEXT NOT NULL DEFAULT ''")
        if "allergens" not in item_columns:
            con.execute("ALTER TABLE items ADD COLUMN allergens TEXT NOT NULL DEFAULT ''")
        if "sold_out" not in item_columns:
            con.execute("ALTER TABLE items ADD COLUMN sold_out INTEGER NOT NULL DEFAULT 0")
        if "stand_id" not in item_columns:
            con.execute("ALTER TABLE items ADD COLUMN stand_id INTEGER REFERENCES stands(id) ON DELETE SET NULL")
        for name in ("name_en", "description_en"):
            if name not in item_columns:
                con.execute(f"ALTER TABLE items ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
        for name in ("available_from", "available_until"):
            if name not in item_columns:
                con.execute(f"ALTER TABLE items ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
        stand_columns = {row["name"] for row in con.execute("PRAGMA table_info(stands)")}
        stand_migrations = {
            "name_en": "TEXT NOT NULL DEFAULT ''", "description_en": "TEXT NOT NULL DEFAULT ''",
            "opening_hours": "TEXT NOT NULL DEFAULT ''", "contact": "TEXT NOT NULL DEFAULT ''",
            "status": "TEXT NOT NULL DEFAULT 'open'", "image_filename": "TEXT NOT NULL DEFAULT ''",
            "marker_id": "INTEGER REFERENCES map_markers(id) ON DELETE SET NULL",
        }
        for name, definition in stand_migrations.items():
            if name not in stand_columns:
                con.execute(f"ALTER TABLE stands ADD COLUMN {name} {definition}")

    # One lightweight local database snapshot per day; keep the newest 14.
    daily_backup = backup_dir / f"events-{time.strftime('%Y%m%d')}.sqlite3"
    if not daily_backup.exists():
        temporary_backup = backup_dir / f".{daily_backup.name}.{secrets.token_hex(4)}.tmp"
        source = sqlite3.connect(app.config["DATABASE"])
        target = sqlite3.connect(temporary_backup)
        source.backup(target)
        target.close()
        source.close()
        os.replace(temporary_backup, daily_backup)
    for old_backup in sorted(backup_dir.glob("events-*.sqlite3"))[:-14]:
        old_backup.unlink(missing_ok=True)

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
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if request.headers.get("Sec-Fetch-Site") == "cross-site" or not valid_origin():
                abort(403)

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; form-action 'self'; frame-ancestors 'none'"
        if request.endpoint and request.endpoint.startswith(("admin", "login", "setup", "backup", "change_password")):
            response.headers["Cache-Control"] = "private, no-store"
        if request.is_secure or request.headers.get("X-Forwarded-Proto", "").split(",")[-1].strip() == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.get("/")
    def home():
        now = time.strftime("%Y-%m-%dT%H:%M")
        with db() as con:
            events = con.execute("SELECT * FROM events WHERE published=1 AND (publish_from='' OR publish_from<=?) AND (publish_until='' OR publish_until>=?) ORDER BY id DESC", (now, now)).fetchall()
        return render_template("home.html", events=events)

    @app.get("/e/<slug>")
    def event_page(slug):
        now = time.strftime("%Y-%m-%dT%H:%M")
        with db() as con:
            event = con.execute("SELECT * FROM events WHERE slug=? AND published=1 AND (publish_from='' OR publish_from<=?) AND (publish_until='' OR publish_until>=?)", (slug, now, now)).fetchone()
            if not event:
                abort(404)
            items = con.execute("SELECT i.*,s.name stand_name,s.name_en stand_name_en,s.kind stand_kind,s.status stand_status FROM items i LEFT JOIN stands s ON s.id=i.stand_id WHERE i.event_id=? AND i.available=1 AND (i.available_from='' OR i.available_from<=?) AND (i.available_until='' OR i.available_until>=?) AND (i.stand_id IS NULL OR s.active=1) ORDER BY i.category,i.sort_order,i.id", (event["id"], now, now)).fetchall()
            stands = con.execute("SELECT * FROM stands WHERE event_id=? AND active=1 ORDER BY sort_order,id", (event["id"],)).fetchall()
            markers = con.execute("SELECT * FROM map_markers WHERE event_id=? ORDER BY id", (event["id"],)).fetchall()
        groups = {}
        for item in items:
            groups.setdefault(item["category"], []).append(item)
        has_general_items = any(item["stand_id"] is None for item in items)
        language = "en" if request.args.get("lang") == "en" else "de"
        marker_stands = {stand["marker_id"]: stand["id"] for stand in stands if stand["marker_id"]}
        return render_template("event.html", event=event, groups=groups, markers=markers,
                               stands=stands, has_general_items=has_general_items,
                               language=language, selected_stand=request.args.get("stand", "all"),
                               marker_stands=marker_stands)

    @app.get("/e/<slug>/map")
    def event_map(slug):
        with db() as con:
            event = con.execute("SELECT map_filename FROM events WHERE slug=? AND published=1", (slug,)).fetchone()
        if not event or not event["map_filename"]:
            abort(404)
        return send_from_directory(map_dir, event["map_filename"], max_age=3600)

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

    @app.get("/e/<slug>/stands/<int:stand_id>/qr.png")
    def stand_qr(slug, stand_id):
        with db() as con:
            stand = con.execute("SELECT s.id FROM stands s JOIN events e ON e.id=s.event_id WHERE e.slug=? AND s.id=?", (slug, stand_id)).fetchone()
        if not stand:
            abort(404)
        base = app.config["PUBLIC_URL"] or request.host_url.rstrip("/")
        image = qrcode.make(f"{base}{url_for('event_page', slug=slug)}?stand={stand_id}")
        output = io.BytesIO()
        image.save(output, format="PNG")
        output.seek(0)
        return send_file(output, mimetype="image/png", download_name=f"qr-stand-{stand_id}.png")

    @app.get("/e/<slug>/stands/<int:stand_id>/image")
    def stand_image(slug, stand_id):
        with db() as con:
            stand = con.execute("SELECT s.image_filename FROM stands s JOIN events e ON e.id=s.event_id WHERE e.slug=? AND s.id=? AND s.active=1", (slug, stand_id)).fetchone()
        if not stand or not stand["image_filename"]:
            abort(404)
        return send_from_directory(stand_dir, stand["image_filename"], max_age=3600)

    @app.route("/admin/login", methods=["GET", "POST"])
    def login():
        refresh_password_state()
        if app.config["NEEDS_SETUP"]:
            return redirect(url_for("setup"))
        if request.method == "POST":
            key = request.remote_addr or "unknown"
            queue = login_attempts[key]
            now = time.time()
            while queue and now - queue[0] > 600:
                queue.popleft()
            if len(queue) >= 10:
                flash("Zu viele Versuche. Bitte zehn Minuten warten.", "error")
                return render_template("login.html"), 429
            supplied = request.form.get("password", "")
            configured = app.config["ADMIN_PASSWORD"]
            valid = check_password_hash(configured, supplied) if configured.startswith(("scrypt:", "pbkdf2:")) else secrets.compare_digest(supplied, configured)
            if valid:
                queue.clear()
                session.clear()
                session["admin"] = True
                session.permanent = True
                return redirect(url_for("admin"))
            queue.append(now)
            flash("Passwort falsch.", "error")
        return render_template("login.html")

    @app.route("/admin/setup", methods=["GET", "POST"])
    def setup():
        refresh_password_state()
        if not app.config["NEEDS_SETUP"]:
            return redirect(url_for("admin") if session.get("admin") else url_for("login"))
        if request.method == "POST":
            password = request.form.get("password", "")
            confirmation = request.form.get("confirmation", "")
            if len(password) < 12:
                flash("Das Passwort muss mindestens 12 Zeichen haben.", "error")
            elif password != confirmation:
                flash("Die beiden Passwörter stimmen nicht überein.", "error")
            else:
                hashed = generate_password_hash(password)
                write_admin_hash(hashed)
                app.config["ADMIN_PASSWORD"] = hashed
                app.config["NEEDS_SETUP"] = False
                session.clear()
                session["admin"] = True
                session.permanent = True
                flash("Die Einrichtung ist abgeschlossen.", "success")
                return redirect(url_for("admin"))
        return render_template("setup.html")

    @app.post("/admin/logout")
    def logout():
        session.clear()
        return redirect(url_for("home"))

    @app.get("/admin")
    def admin():
        admin_required()
        with db() as con:
            events = con.execute("SELECT e.*,COUNT(i.id) item_count FROM events e LEFT JOIN items i ON i.event_id=e.id GROUP BY e.id ORDER BY e.id DESC").fetchall()
            stats = con.execute("SELECT COUNT(*) events,(SELECT COUNT(*) FROM events WHERE published=1) published,(SELECT COUNT(*) FROM items) items,(SELECT COUNT(*) FROM map_markers) markers FROM events").fetchone()
        return render_template("admin.html", events=events, stats=stats)

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
            items = con.execute("SELECT i.*,s.name stand_name FROM items i LEFT JOIN stands s ON s.id=i.stand_id WHERE i.event_id=? ORDER BY i.category,i.sort_order,i.id", (event_id,)).fetchall()
            stands = con.execute("SELECT s.*,COUNT(i.id) item_count FROM stands s LEFT JOIN items i ON i.stand_id=s.id WHERE s.event_id=? GROUP BY s.id ORDER BY s.sort_order,s.id", (event_id,)).fetchall()
            markers = con.execute("SELECT * FROM map_markers WHERE event_id=? ORDER BY id", (event_id,)).fetchall()
        if not event:
            abort(404)
        return render_template("edit.html", event=event, items=items, markers=markers, stands=stands)

    @app.post("/admin/events/<int:event_id>/stands")
    def add_stand(event_id):
        admin_required()
        name = request.form.get("name", "").strip()[:80]
        kind = request.form.get("kind", "stand")
        accent = request.form.get("accent", "#1f6f5c")
        if not name:
            flash("Der Stand benötigt einen Namen.", "error")
            return redirect(url_for("edit_event", event_id=event_id) + "#staende")
        if kind not in {"stand", "essen", "getraenk", "handwerk", "verein", "info"}:
            kind = "stand"
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", accent):
            accent = "#1f6f5c"
        with db() as con:
            if not con.execute("SELECT 1 FROM events WHERE id=?", (event_id,)).fetchone():
                abort(404)
            con.execute("INSERT INTO stands(event_id,name,description,name_en,description_en,kind,accent,sort_order,opening_hours,contact,status,marker_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
                event_id, name, request.form.get("description", "").strip()[:180],
                request.form.get("name_en", "").strip()[:80], request.form.get("description_en", "").strip()[:180],
                kind, accent, form_int("sort_order"), request.form.get("opening_hours", "").strip()[:180],
                request.form.get("contact", "").strip()[:160], "open", None))
        flash("Stand wurde angelegt.", "success")
        return redirect(url_for("edit_event", event_id=event_id) + "#staende")

    @app.post("/admin/events/<int:event_id>/stands/<int:stand_id>/update")
    def update_stand(event_id, stand_id):
        admin_required()
        name = request.form.get("name", "").strip()[:80]
        kind = request.form.get("kind", "stand")
        accent = request.form.get("accent", "#1f6f5c")
        if not name:
            flash("Der Stand benötigt einen Namen.", "error")
            return redirect(url_for("edit_event", event_id=event_id) + "#staende")
        if kind not in {"stand", "essen", "getraenk", "handwerk", "verein", "info"}:
            kind = "stand"
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", accent):
            accent = "#1f6f5c"
        status = request.form.get("status", "open")
        if status not in {"open", "closed", "sold_out"}:
            status = "open"
        with db() as con:
            try:
                marker_id = int(request.form.get("marker_id", "") or 0) or None
            except ValueError:
                marker_id = None
            if marker_id and not con.execute("SELECT 1 FROM map_markers WHERE id=? AND event_id=?", (marker_id, event_id)).fetchone():
                marker_id = None
            result = con.execute("UPDATE stands SET name=?,description=?,name_en=?,description_en=?,kind=?,accent=?,sort_order=?,active=?,opening_hours=?,contact=?,status=?,marker_id=? WHERE id=? AND event_id=?", (
                name, request.form.get("description", "").strip()[:180], request.form.get("name_en", "").strip()[:80],
                request.form.get("description_en", "").strip()[:180], kind, accent, form_int("sort_order"),
                1 if request.form.get("active") == "1" else 0, request.form.get("opening_hours", "").strip()[:180],
                request.form.get("contact", "").strip()[:160], status, marker_id, stand_id, event_id))
            if not result.rowcount:
                abort(404)
        flash("Stand wurde gespeichert.", "success")
        return redirect(url_for("edit_event", event_id=event_id) + "#staende")

    @app.post("/admin/events/<int:event_id>/stands/<int:stand_id>/delete")
    def delete_stand(event_id, stand_id):
        admin_required()
        with db() as con:
            stand = con.execute("SELECT image_filename FROM stands WHERE id=? AND event_id=?", (stand_id, event_id)).fetchone()
            con.execute("UPDATE items SET stand_id=NULL WHERE event_id=? AND stand_id=?", (event_id, stand_id))
            con.execute("DELETE FROM stands WHERE id=? AND event_id=?", (stand_id, event_id))
        if stand and stand["image_filename"]:
            try:
                (stand_dir / stand["image_filename"]).unlink()
            except FileNotFoundError:
                pass
        flash("Stand wurde gelöscht. Seine Artikel sind jetzt allgemein zugeordnet.", "success")
        return redirect(url_for("edit_event", event_id=event_id) + "#staende")

    @app.post("/admin/events/<int:event_id>/stands/reorder")
    def reorder_stands(event_id):
        admin_required()
        order = (request.get_json(silent=True) or {}).get("order", [])
        if not isinstance(order, list) or len(order) > 500:
            return jsonify(ok=False), 400
        with db() as con:
            valid = {row["id"] for row in con.execute("SELECT id FROM stands WHERE event_id=?", (event_id,))}
            cleaned = []
            for value in order:
                try:
                    stand_id = int(value)
                except (TypeError, ValueError):
                    continue
                if stand_id in valid and stand_id not in cleaned:
                    cleaned.append(stand_id)
            for position, stand_id in enumerate(cleaned):
                con.execute("UPDATE stands SET sort_order=? WHERE id=? AND event_id=?", (position, stand_id, event_id))
        return jsonify(ok=True)

    @app.post("/admin/events/<int:event_id>/stands/<int:stand_id>/image")
    def upload_stand_image(event_id, stand_id):
        admin_required()
        upload = request.files.get("image")
        if not upload or not upload.filename:
            flash("Bitte ein Standbild auswählen.", "error")
            return redirect(url_for("edit_event", event_id=event_id) + "#staende")
        data = upload.read(2 * 1024 * 1024 + 1)
        extension = None
        if len(data) <= 2 * 1024 * 1024:
            try:
                with Image.open(io.BytesIO(data)) as image:
                    image.verify()
                    extension = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}.get(image.format)
            except (UnidentifiedImageError, OSError):
                pass
        if not extension:
            flash("Erlaubt sind PNG, JPEG oder WebP bis 2 MB.", "error")
            return redirect(url_for("edit_event", event_id=event_id) + "#staende")
        with db() as con:
            stand = con.execute("SELECT image_filename FROM stands WHERE id=? AND event_id=?", (stand_id, event_id)).fetchone()
            if not stand:
                abort(404)
            filename = f"stand-{event_id}-{stand_id}-{secrets.token_hex(6)}{extension}"
            (stand_dir / filename).write_bytes(data)
            old = stand["image_filename"]
            con.execute("UPDATE stands SET image_filename=? WHERE id=?", (filename, stand_id))
        if old:
            try:
                (stand_dir / old).unlink()
            except FileNotFoundError:
                pass
        flash("Standbild wurde gespeichert.", "success")
        return redirect(url_for("edit_event", event_id=event_id) + "#staende")

    @app.get("/admin/events/<int:event_id>/stands/<int:stand_id>/sign")
    def stand_sign(event_id, stand_id):
        admin_required()
        with db() as con:
            event = con.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
            stand = con.execute("SELECT * FROM stands WHERE id=? AND event_id=?", (stand_id, event_id)).fetchone()
        if not event or not stand:
            abort(404)
        return render_template("stand_sign.html", event=event, stand=stand)

    @app.post("/admin/events/<int:event_id>/map")
    def upload_map(event_id):
        admin_required()
        upload = request.files.get("map")
        if not upload or not upload.filename:
            flash("Bitte ein Planbild auswählen.", "error")
            return redirect(url_for("edit_event", event_id=event_id))
        data = upload.read(2 * 1024 * 1024 + 1)
        extension = None
        if len(data) <= 2 * 1024 * 1024:
            try:
                with Image.open(io.BytesIO(data)) as image:
                    image.verify()
                    extension = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}.get(image.format)
            except (UnidentifiedImageError, OSError):
                pass
        if not extension or len(data) > 2 * 1024 * 1024:
            flash("Erlaubt sind PNG, JPEG oder WebP bis 2 MB.", "error")
            return redirect(url_for("edit_event", event_id=event_id))
        with db() as con:
            event = con.execute("SELECT map_filename FROM events WHERE id=?", (event_id,)).fetchone()
            if not event:
                abort(404)
            filename = f"event-{event_id}-{secrets.token_hex(6)}{extension}"
            (map_dir / filename).write_bytes(data)
            old = event["map_filename"]
            con.execute("UPDATE events SET map_filename=? WHERE id=?", (filename, event_id))
        if old and re.fullmatch(r"event-[0-9]+-[0-9a-f]+\.(png|jpg|webp)", old):
            try:
                (map_dir / old).unlink()
            except FileNotFoundError:
                pass
        flash("Plan wurde gespeichert.", "success")
        return redirect(url_for("edit_event", event_id=event_id))

    @app.get("/admin/events/<int:event_id>/map")
    def admin_map(event_id):
        admin_required()
        with db() as con:
            event = con.execute("SELECT map_filename FROM events WHERE id=?", (event_id,)).fetchone()
        if not event or not event["map_filename"]:
            abort(404)
        return send_from_directory(map_dir, event["map_filename"], max_age=0)

    @app.post("/admin/events/<int:event_id>/markers")
    def add_marker(event_id):
        admin_required()
        label = request.form.get("label", "").strip()[:80]
        description = request.form.get("description", "").strip()[:180]
        kind = request.form.get("kind", "stand")
        if kind not in {"stand", "essen", "getraenk", "wc", "eingang", "info", "hilfe"}:
            kind = "stand"
        try:
            x = float(request.form.get("x", ""))
            y = float(request.form.get("y", ""))
        except ValueError:
            x = y = -1
        if not label or not 0 <= x <= 100 or not 0 <= y <= 100:
            flash("Auf den Plan tippen und einen Namen für den Punkt eingeben.", "error")
            return redirect(url_for("edit_event", event_id=event_id))
        with db() as con:
            event = con.execute("SELECT map_filename FROM events WHERE id=?", (event_id,)).fetchone()
            if not event or not event["map_filename"]:
                flash("Bitte zuerst ein Planbild hochladen.", "error")
                return redirect(url_for("edit_event", event_id=event_id))
            con.execute("INSERT INTO map_markers(event_id,label,description,kind,x_percent,y_percent) VALUES(?,?,?,?,?,?)", (event_id, label, description, kind, x, y))
        return redirect(url_for("edit_event", event_id=event_id))

    @app.post("/admin/events/<int:event_id>/markers/<int:marker_id>/delete")
    def delete_marker(event_id, marker_id):
        admin_required()
        with db() as con:
            con.execute("DELETE FROM map_markers WHERE id=? AND event_id=?", (marker_id, event_id))
        return redirect(url_for("edit_event", event_id=event_id))

    @app.post("/admin/events/<int:event_id>/toggle")
    def toggle_event(event_id):
        admin_required()
        with db() as con:
            con.execute("UPDATE events SET published=1-published WHERE id=?", (event_id,))
        return redirect(url_for("edit_event", event_id=event_id))

    @app.post("/admin/events/<int:event_id>/update")
    def update_event(event_id):
        admin_required()
        title = request.form.get("title", "").strip()[:80]
        accent = request.form.get("accent", "#8b1e3f")
        if not title:
            flash("Der Eventtitel darf nicht leer sein.", "error")
            return redirect(url_for("edit_event", event_id=event_id))
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", accent):
            accent = "#8b1e3f"
        with db() as con:
            result = con.execute("UPDATE events SET title=?,subtitle=?,date_text=?,location=?,opening_hours=?,accent=?,publish_from=?,publish_until=? WHERE id=?", (
                title, request.form.get("subtitle", "").strip()[:160], request.form.get("date_text", "").strip()[:60],
                request.form.get("location", "").strip()[:100], request.form.get("opening_hours", "").strip()[:180], accent,
                request.form.get("publish_from", "")[:16], request.form.get("publish_until", "")[:16], event_id))
            if not result.rowcount:
                abort(404)
        flash("Eventdaten wurden gespeichert.", "success")
        return redirect(url_for("edit_event", event_id=event_id))

    @app.post("/admin/events/<int:event_id>/clone")
    def clone_event(event_id):
        admin_required()
        new_slug = request.form.get("slug", "").strip().lower()
        if not SLUG_RE.fullmatch(new_slug):
            flash("Bitte eine gültige neue Adresse eingeben.", "error")
            return redirect(url_for("edit_event", event_id=event_id))
        try:
            with db() as con:
                source = con.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
                if not source:
                    abort(404)
                cursor = con.execute("INSERT INTO events(slug,title,subtitle,date_text,location,opening_hours,accent,published) VALUES(?,?,?,?,?,?,?,0)", (
                    new_slug, source["title"] + " – Kopie", source["subtitle"], source["date_text"], source["location"], source["opening_hours"], source["accent"]))
                new_id = cursor.lastrowid
                stand_map = {}
                for stand in con.execute("SELECT * FROM stands WHERE event_id=? ORDER BY id", (event_id,)).fetchall():
                    created = con.execute("INSERT INTO stands(event_id,name,description,name_en,description_en,kind,accent,sort_order,active,opening_hours,contact,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
                        new_id, stand["name"], stand["description"], stand["name_en"], stand["description_en"], stand["kind"],
                        stand["accent"], stand["sort_order"], stand["active"], stand["opening_hours"], stand["contact"], stand["status"]))
                    stand_map[stand["id"]] = created.lastrowid
                for item in con.execute("SELECT * FROM items WHERE event_id=? ORDER BY id", (event_id,)).fetchall():
                    con.execute("INSERT INTO items(event_id,category,name,description,name_en,description_en,price_cents,sort_order,available,labels,allergens,sold_out,stand_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,0,?)", (
                        new_id, item["category"], item["name"], item["description"], item["name_en"], item["description_en"],
                        item["price_cents"], item["sort_order"], item["available"], item["labels"], item["allergens"], stand_map.get(item["stand_id"])))
        except sqlite3.IntegrityError:
            flash("Diese Adresse wird bereits verwendet.", "error")
            return redirect(url_for("edit_event", event_id=event_id))
        return redirect(url_for("edit_event", event_id=new_id))

    @app.get("/admin/events/<int:event_id>/items.csv")
    def export_items(event_id):
        admin_required()
        with db() as con:
            rows = con.execute("SELECT i.category,i.name,i.description,i.price_cents,i.labels,i.allergens,i.sort_order,i.sold_out,s.name stand_name FROM items i LEFT JOIN stands s ON s.id=i.stand_id WHERE i.event_id=? ORDER BY i.sort_order,i.id", (event_id,)).fetchall()
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")
        writer.writerow(["Stand", "Kategorie", "Name", "Beschreibung", "Preis", "Kennzeichnungen", "Allergene", "Reihenfolge", "Ausverkauft"])
        for row in rows:
            writer.writerow([row["stand_name"] or "", row["category"], row["name"], row["description"], f'{row["price_cents"]/100:.2f}', row["labels"], row["allergens"], row["sort_order"], row["sold_out"]])
        return Response("\ufeff" + output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f'attachment; filename="preisliste-{event_id}.csv"'})

    @app.post("/admin/events/<int:event_id>/items/import")
    def import_items(event_id):
        admin_required()
        upload = request.files.get("csv")
        if not upload:
            abort(400)
        try:
            text = upload.read(512 * 1024).decode("utf-8-sig")
            rows = list(csv.DictReader(io.StringIO(text), delimiter=";"))[:1000]
            with db() as con:
                stands_by_name = {stand["name"].casefold(): stand["id"] for stand in con.execute("SELECT id,name FROM stands WHERE event_id=?", (event_id,))}
                values = []
                for row in rows:
                    cents = int((Decimal(row["Preis"].replace(",", ".")) * 100).quantize(Decimal("1")))
                    stand_name = row.get("Stand", "").strip()[:80]
                    stand_id = stands_by_name.get(stand_name.casefold()) if stand_name else None
                    if stand_name and stand_id is None:
                        created = con.execute("INSERT INTO stands(event_id,name) VALUES(?,?)", (event_id, stand_name))
                        stand_id = created.lastrowid
                        stands_by_name[stand_name.casefold()] = stand_id
                    values.append((event_id, row.get("Kategorie", "Allgemein")[:60], row["Name"][:100], row.get("Beschreibung", "")[:180], cents, int(row.get("Reihenfolge", 0) or 0), row.get("Kennzeichnungen", "")[:100], row.get("Allergene", "")[:100], 1 if row.get("Ausverkauft") in {"1", "ja", "true"} else 0, stand_id))
                con.executemany("INSERT INTO items(event_id,category,name,description,price_cents,sort_order,labels,allergens,sold_out,stand_id) VALUES(?,?,?,?,?,?,?,?,?,?)", values)
            flash(f"{len(values)} Artikel wurden importiert.", "success")
        except (KeyError, ValueError, InvalidOperation, UnicodeDecodeError):
            flash("CSV konnte nicht gelesen werden. Bitte zuerst eine Vorlage exportieren.", "error")
        return redirect(url_for("edit_event", event_id=event_id))

    @app.get("/admin/backup.zip")
    def backup():
        admin_required()
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(app.config["DATABASE"], "events.sqlite3")
            for path in map_dir.glob("event-*"):
                if path.is_file():
                    archive.write(path, f"maps/{path.name}")
            for path in stand_dir.glob("stand-*"):
                if path.is_file():
                    archive.write(path, f"stands/{path.name}")
            archive.writestr("backup.json", json.dumps({"version": APP_VERSION, "created": int(time.time())}))
        output.seek(0)
        return send_file(output, mimetype="application/zip", as_attachment=True, download_name=f"event-preisliste-{time.strftime('%Y%m%d')}.zip")

    @app.post("/admin/backup/restore")
    def restore_backup():
        admin_required()
        upload = request.files.get("backup")
        if not upload:
            abort(400)
        data = upload.read(100 * 1024 * 1024 + 1)
        if len(data) > 100 * 1024 * 1024:
            flash("Das Backup ist größer als 100 MB.", "error")
            return redirect(url_for("admin") + "#settings")
        try:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    if sum(info.file_size for info in archive.infolist()) > 200 * 1024 * 1024:
                        raise ValueError
                    allowed = [name for name in archive.namelist() if name == "events.sqlite3" or re.fullmatch(r"(?:maps|stands)/[A-Za-z0-9._-]+", name)]
                    if "events.sqlite3" not in allowed:
                        raise ValueError
                    for name in allowed:
                        archive.extract(name, root)
                candidate = root / "events.sqlite3"
                check = sqlite3.connect(candidate)
                integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
                check.close()
                if integrity != "ok":
                    raise ValueError
                shutil.copy2(app.config["DATABASE"], backup_dir / f"before-restore-{time.strftime('%Y%m%d-%H%M%S')}.sqlite3")
                os.replace(candidate, app.config["DATABASE"])
                for folder, target in (("maps", map_dir), ("stands", stand_dir)):
                    source = root / folder
                    if source.exists():
                        for path in source.iterdir():
                            if path.is_file():
                                shutil.copy2(path, target / path.name)
            flash("Backup wurde geprüft und wiederhergestellt.", "success")
        except (zipfile.BadZipFile, ValueError, sqlite3.DatabaseError, OSError):
            flash("Dieses Backup ist ungültig oder beschädigt.", "error")
        return redirect(url_for("admin") + "#settings")

    @app.post("/admin/password")
    def change_password():
        admin_required()
        new_password = request.form.get("password", "")
        if len(new_password) < 12:
            flash("Das neue Passwort muss mindestens 12 Zeichen haben.", "error")
        else:
            hashed = generate_password_hash(new_password)
            write_admin_hash(hashed)
            app.config["ADMIN_PASSWORD"] = hashed
            session.clear()
            flash("Passwort geändert. Bitte neu anmelden.", "success")
            return redirect(url_for("login"))
        return redirect(url_for("admin"))

    @app.get("/manifest.webmanifest")
    def manifest():
        return {
            "name": "Event-Preisliste", "short_name": "Preisliste", "start_url": "/",
            "display": "standalone", "background_color": "#f7f4ed", "theme_color": "#17332c",
            "icons": [{"src": url_for("static", filename="logo.svg"), "sizes": "any", "type": "image/svg+xml"}],
        }, 200, {"Content-Type": "application/manifest+json"}

    @app.get("/service-worker.js")
    def service_worker():
        script = "const C='event-preisliste-v5';self.addEventListener('install',e=>e.waitUntil(caches.open(C).then(c=>c.addAll(['/','/static/style.css','/static/admin.css','/static/extras.css','/static/logo.svg']))));self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==C).map(k=>caches.delete(k))))));self.addEventListener('fetch',e=>{if(e.request.method==='GET')e.respondWith(fetch(e.request).then(r=>{let x=r.clone();caches.open(C).then(c=>c.put(e.request,x));return r}).catch(()=>caches.match(e.request)))})"
        return Response(script, mimetype="application/javascript", headers={"Service-Worker-Allowed": "/"})

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
            stand_id = selected_stand_id(con, event_id)
            con.execute("INSERT INTO items(event_id,category,name,description,name_en,description_en,price_cents,sort_order,labels,allergens,stand_id,available_from,available_until) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                event_id, request.form.get("category", "Allgemein").strip()[:60] or "Allgemein", name,
                request.form.get("description", "").strip()[:180], request.form.get("name_en", "").strip()[:100],
                request.form.get("description_en", "").strip()[:180], cents, form_int("sort_order"),
                request.form.get("labels", "").strip()[:100], request.form.get("allergens", "").strip()[:100], stand_id,
                request.form.get("available_from", "")[:16], request.form.get("available_until", "")[:16]))
        return redirect(url_for("edit_event", event_id=event_id))

    @app.post("/admin/events/<int:event_id>/items/<int:item_id>/update")
    def update_item(event_id, item_id):
        admin_required()
        name = request.form.get("name", "").strip()[:100]
        try:
            cents = int((Decimal(request.form.get("price", "").replace(",", ".")) * 100).quantize(Decimal("1")))
            if not 0 <= cents <= 10_000_000:
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            flash("Bitte einen gültigen Preis eingeben.", "error")
            return redirect(url_for("edit_event", event_id=event_id))
        if not name:
            flash("Der Artikel benötigt einen Namen.", "error")
            return redirect(url_for("edit_event", event_id=event_id))
        with db() as con:
            stand_id = selected_stand_id(con, event_id)
            result = con.execute("UPDATE items SET category=?,name=?,description=?,name_en=?,description_en=?,price_cents=?,sort_order=?,labels=?,allergens=?,sold_out=?,stand_id=?,available_from=?,available_until=? WHERE id=? AND event_id=?", (
                request.form.get("category", "Allgemein").strip()[:60] or "Allgemein", name,
                request.form.get("description", "").strip()[:180], request.form.get("name_en", "").strip()[:100],
                request.form.get("description_en", "").strip()[:180], cents, form_int("sort_order"),
                request.form.get("labels", "").strip()[:100], request.form.get("allergens", "").strip()[:100],
                1 if request.form.get("sold_out") == "1" else 0, stand_id,
                request.form.get("available_from", "")[:16], request.form.get("available_until", "")[:16], item_id, event_id))
            if not result.rowcount:
                abort(404)
        flash("Artikel wurde gespeichert.", "success")
        return redirect(url_for("edit_event", event_id=event_id))

    @app.post("/admin/events/<int:event_id>/items/<int:item_id>/delete")
    def delete_item(event_id, item_id):
        admin_required()
        with db() as con:
            con.execute("DELETE FROM items WHERE id=? AND event_id=?", (item_id, event_id))
        return redirect(url_for("edit_event", event_id=event_id))

    @app.post("/admin/events/<int:event_id>/items/<int:item_id>/translation")
    def update_item_translation(event_id, item_id):
        admin_required()
        with db() as con:
            result = con.execute("UPDATE items SET name_en=?,description_en=? WHERE id=? AND event_id=?", (
                request.form.get("name_en", "").strip()[:100], request.form.get("description_en", "").strip()[:180],
                item_id, event_id))
            if not result.rowcount:
                abort(404)
        flash("Englische Übersetzung wurde gespeichert.", "success")
        return redirect(url_for("edit_event", event_id=event_id) + "#uebersetzungen")

    @app.get("/health")
    def health():
        return {"ok": True, "version": APP_VERSION}

    return app
