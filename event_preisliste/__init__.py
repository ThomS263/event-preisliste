import io
import csv
import json
import os
import re
import secrets
import sqlite3
import time
import zipfile
from collections import defaultdict, deque
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

import qrcode
from PIL import Image, UnidentifiedImageError
from flask import (Flask, abort, flash, redirect, render_template, request,
                   Response, send_file, send_from_directory, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash


SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$|^[a-z0-9]$")


def create_app(test_config=None):
    app = Flask(__name__)
    data_dir = Path(os.environ.get("EVENT_DATA_DIR", "/data"))
    if test_config:
        data_dir = Path(test_config.get("DATA_DIR", data_dir))
    data_dir.mkdir(parents=True, exist_ok=True)
    map_dir = data_dir / "maps"
    map_dir.mkdir(exist_ok=True)
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
    if password_hash_file.exists():
        admin_password = password_hash_file.read_text().strip()
    elif not admin_password:
        if password_file.exists():
            admin_password = password_file.read_text().strip()
        else:
            admin_password = secrets.token_urlsafe(18)
            password_file.write_text(admin_password)
            password_file.chmod(0o600)
    app.secret_key = secret
    app.config.update(
        DATABASE=str(data_dir / "events.sqlite3"),
        ADMIN_PASSWORD=admin_password,
        PUBLIC_URL=os.environ.get("EVENT_PUBLIC_URL", "").rstrip("/"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)
    login_attempts = defaultdict(deque)

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
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; form-action 'self'; frame-ancestors 'none'"
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
            items = con.execute("SELECT * FROM items WHERE event_id=? AND available=1 ORDER BY category,sort_order,id", (event["id"],)).fetchall()
            markers = con.execute("SELECT * FROM map_markers WHERE event_id=? ORDER BY id", (event["id"],)).fetchall()
        groups = {}
        for item in items:
            groups.setdefault(item["category"], []).append(item)
        return render_template("event.html", event=event, groups=groups, markers=markers)

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

    @app.route("/admin/login", methods=["GET", "POST"])
    def login():
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
                return redirect(url_for("admin"))
            queue.append(now)
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
            items = con.execute("SELECT * FROM items WHERE event_id=? ORDER BY category,sort_order,id", (event_id,)).fetchall()
            markers = con.execute("SELECT * FROM map_markers WHERE event_id=? ORDER BY id", (event_id,)).fetchall()
        if not event:
            abort(404)
        return render_template("edit.html", event=event, items=items, markers=markers)

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
                con.execute("INSERT INTO items(event_id,category,name,description,price_cents,sort_order,available,labels,allergens,sold_out) SELECT ?,category,name,description,price_cents,sort_order,available,labels,allergens,0 FROM items WHERE event_id=?", (new_id, event_id))
        except sqlite3.IntegrityError:
            flash("Diese Adresse wird bereits verwendet.", "error")
            return redirect(url_for("edit_event", event_id=event_id))
        return redirect(url_for("edit_event", event_id=new_id))

    @app.get("/admin/events/<int:event_id>/items.csv")
    def export_items(event_id):
        admin_required()
        with db() as con:
            rows = con.execute("SELECT category,name,description,price_cents,labels,allergens,sort_order,sold_out FROM items WHERE event_id=? ORDER BY sort_order,id", (event_id,)).fetchall()
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")
        writer.writerow(["Kategorie", "Name", "Beschreibung", "Preis", "Kennzeichnungen", "Allergene", "Reihenfolge", "Ausverkauft"])
        for row in rows:
            writer.writerow([row["category"], row["name"], row["description"], f'{row["price_cents"]/100:.2f}', row["labels"], row["allergens"], row["sort_order"], row["sold_out"]])
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
            values = []
            for row in rows:
                cents = int((Decimal(row["Preis"].replace(",", ".")) * 100).quantize(Decimal("1")))
                values.append((event_id, row.get("Kategorie", "Allgemein")[:60], row["Name"][:100], row.get("Beschreibung", "")[:180], cents, int(row.get("Reihenfolge", 0) or 0), row.get("Kennzeichnungen", "")[:100], row.get("Allergene", "")[:100], 1 if row.get("Ausverkauft") in {"1", "ja", "true"} else 0))
            with db() as con:
                con.executemany("INSERT INTO items(event_id,category,name,description,price_cents,sort_order,labels,allergens,sold_out) VALUES(?,?,?,?,?,?,?,?,?)", values)
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
            archive.writestr("backup.json", json.dumps({"version": "0.4.2", "created": int(time.time())}))
        output.seek(0)
        return send_file(output, mimetype="application/zip", as_attachment=True, download_name=f"event-preisliste-{time.strftime('%Y%m%d')}.zip")

    @app.post("/admin/password")
    def change_password():
        admin_required()
        new_password = request.form.get("password", "")
        if len(new_password) < 12:
            flash("Das neue Passwort muss mindestens 12 Zeichen haben.", "error")
        else:
            hashed = generate_password_hash(new_password)
            password_hash_file.write_text(hashed)
            password_hash_file.chmod(0o600)
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
        script = "const C='event-preisliste-v1';self.addEventListener('install',e=>e.waitUntil(caches.open(C).then(c=>c.addAll(['/','/static/style.css','/static/admin.css']))));self.addEventListener('fetch',e=>{if(e.request.method==='GET')e.respondWith(fetch(e.request).then(r=>{let x=r.clone();caches.open(C).then(c=>c.put(e.request,x));return r}).catch(()=>caches.match(e.request)))})"
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
            con.execute("INSERT INTO items(event_id,category,name,description,price_cents,sort_order,labels,allergens) VALUES(?,?,?,?,?,?,?,?)", (
                event_id, request.form.get("category", "Allgemein").strip()[:60] or "Allgemein", name,
                request.form.get("description", "").strip()[:180], cents, int(request.form.get("sort_order", 0) or 0),
                request.form.get("labels", "").strip()[:100], request.form.get("allergens", "").strip()[:100]))
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
            result = con.execute("UPDATE items SET category=?,name=?,description=?,price_cents=?,sort_order=?,labels=?,allergens=?,sold_out=? WHERE id=? AND event_id=?", (
                request.form.get("category", "Allgemein").strip()[:60] or "Allgemein", name,
                request.form.get("description", "").strip()[:180], cents, int(request.form.get("sort_order", 0) or 0),
                request.form.get("labels", "").strip()[:100], request.form.get("allergens", "").strip()[:100],
                1 if request.form.get("sold_out") == "1" else 0, item_id, event_id))
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

    @app.get("/health")
    def health():
        return {"ok": True, "version": "0.4.2"}

    return app
