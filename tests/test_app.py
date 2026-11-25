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
