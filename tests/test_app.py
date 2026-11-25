import io
from pathlib import Path

from PIL import Image
import yaml

from event_preisliste import create_app


def app(tmp_path):
    return create_app({"TESTING": True, "DATA_DIR": tmp_path, "ADMIN_PASSWORD": "test-passwort"})


def login(client):
    return client.post("/admin/login", data={"password": "test-passwort"})


def test_health_and_empty_home(tmp_path):
    client = app(tmp_path).test_client()
    assert client.get("/health").json["ok"] is True
    assert "keine Veranstaltung" in client.get("/").get_data(as_text=True)


def test_admin_event_item_and_qr_flow(tmp_path):
    client = app(tmp_path).test_client()
    assert client.get("/admin").status_code == 401
    assert login(client).status_code == 302
    response = client.post("/admin/events", data={
        "title": "Adventmarkt", "slug": "adventmarkt", "subtitle": "Punsch und Essen",
        "date_text": "28. November", "location": "Dorfplatz", "accent": "#8b1e3f",
    })
    assert response.status_code == 302
    response = client.post("/admin/events/1/items", data={
        "category": "Getränke", "name": "Kinderpunsch", "description": "0,25 Liter", "price": "3,50",
    })
    assert response.status_code == 302
    assert client.get("/e/adventmarkt").status_code == 404
    client.post("/admin/events/1/toggle")
    page = client.get("/e/adventmarkt")
    assert page.status_code == 200
    assert "Kinderpunsch" in page.get_data(as_text=True)
    qr = client.get("/e/adventmarkt/qr.png")
    assert qr.status_code == 200
    assert qr.mimetype == "image/png"


def test_rejects_invalid_slug_and_cross_origin(tmp_path):
    client = app(tmp_path).test_client()
    login(client)
    client.post("/admin/events", data={"title": "Test", "slug": "Nicht gültig"})
    assert "Noch keine Veranstaltung" in client.get("/admin").get_data(as_text=True)
    response = client.post("/admin/events", headers={"Origin": "https://evil.example"}, data={"title": "Test", "slug": "test"})
    assert response.status_code == 403


def test_interactive_map_upload_and_marker(tmp_path):
    client = app(tmp_path).test_client()
    login(client)
    client.post("/admin/events", data={"title": "Feuerwehrfest", "slug": "feuerwehrfest"})
    image_data = io.BytesIO()
    Image.new("RGB", (40, 20), "white").save(image_data, format="PNG")
    image_data.seek(0)
    response = client.post("/admin/events/1/map", data={"map": (image_data, "plan.png")}, content_type="multipart/form-data")
    assert response.status_code == 302
    response = client.post("/admin/events/1/markers", data={
        "label": "Getränkestand", "description": "Punsch und Saft", "kind": "getraenk", "x": "25.5", "y": "70.25",
    })
    assert response.status_code == 302
    client.post("/admin/events/1/toggle")
    page = client.get("/e/feuerwehrfest")
    assert "Interaktiver Plan" in page.get_data(as_text=True)
    assert "Getränkestand" in page.get_data(as_text=True)
    assert client.get("/e/feuerwehrfest/map").status_code == 200


def test_admin_can_edit_event_and_mark_item_sold_out(tmp_path):
    client = app(tmp_path).test_client()
    login(client)
    client.post("/admin/events", data={"title": "Markt", "slug": "markt"})
    client.post("/admin/events/1/update", data={
        "title": "Adventmarkt", "subtitle": "Am Dorfplatz", "date_text": "1. Dezember",
        "location": "Dorfplatz", "opening_hours": "10–20 Uhr", "accent": "#225544",
    })
    client.post("/admin/events/1/items", data={"category": "Essen", "name": "Kekse", "price": "2.00"})
    response = client.post("/admin/events/1/items/1/update", data={
        "category": "Essen", "name": "Weihnachtskekse", "description": "Hausgemacht", "price": "2,50",
        "labels": "vegetarisch", "allergens": "A, C", "sort_order": "1", "sold_out": "1",
    })
    assert response.status_code == 302
    client.post("/admin/events/1/toggle")
    page = client.get("/e/markt").get_data(as_text=True)
    assert "Adventmarkt" in page
    assert "10–20 Uhr" in page
    assert "Weihnachtskekse" in page
    assert "Ausverkauft" in page
    assert "vegetarisch" in page
    assert "Allergene: A, C" in page


def test_casaos_manifest_is_installable():
    manifest = yaml.safe_load(Path("Apps/EventPreisliste/docker-compose.yml").read_text())
    service = manifest["services"]["event-preisliste"]
    assert service["image"] == "ghcr.io/thoms263/event-preisliste:0.4.1"
    assert service["ports"][0]["published"] == "8090"
    compose = yaml.safe_load(Path("compose.yaml").read_text())
    assert compose["services"]["event-preisliste"]["ports"] == ["${EVENT_PORT:-8090}:8080"]
    assert "EVENT_PORT=8090" in Path(".env.example").read_text().splitlines()
    assert service["volumes"][0]["target"] == "/data"
    assert manifest["x-casaos"]["main"] == "event-preisliste"


def test_clone_csv_backup_and_pwa(tmp_path):
    client = app(tmp_path).test_client()
    login(client)
    client.post("/admin/events", data={"title": "Markt", "slug": "markt"})
    client.post("/admin/events/1/items", data={"category": "Getränke", "name": "Punsch", "price": "4.50"})
    assert client.post("/admin/events/1/clone", data={"slug": "markt-2027"}).status_code == 302
    exported = client.get("/admin/events/1/items.csv")
    assert exported.status_code == 200 and "Punsch" in exported.get_data(as_text=True)
    backup = client.get("/admin/backup.zip")
    assert backup.status_code == 200 and backup.data.startswith(b"PK")
    assert client.get("/manifest.webmanifest").status_code == 200
    assert "event-preisliste-v1" in client.get("/service-worker.js").get_data(as_text=True)


def test_password_change_and_login_rate_limit(tmp_path):
    client = app(tmp_path).test_client()
    login(client)
    assert client.post("/admin/password", data={"password": "neues-sehr-langes-passwort"}).status_code == 302
    assert client.post("/admin/login", data={"password": "neues-sehr-langes-passwort"}).status_code == 302
    other = app(tmp_path / "other").test_client()
    for _ in range(10):
        other.post("/admin/login", data={"password": "falsch"})
    assert other.post("/admin/login", data={"password": "falsch"}).status_code == 429
