import csv
import io
import re

import pytest

from contest import create_app

VALID = {
    "first_name": "Asha",
    "last_name": "Rao",
    "mobile": "+91 98765 43210",
    "email": "Asha@Example.com",
    "consent": "y",
}


@pytest.fixture
def app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "DATABASE": str(tmp_path / "t.sqlite3"),
            "ADMIN_TOKEN": "s3cret-token",
        }
    )


@pytest.fixture
def client(app):
    return app.test_client()


def entries(app):
    import sqlite3

    with sqlite3.connect(app.config["DATABASE"]) as db:
        return db.execute("select first_name, last_name, mobile, email from entries").fetchall()


def test_landing_page_links_to_registration(client):
    page = client.get("/").get_data(as_text=True)
    assert "The Itchy Challenge" in page and 'href="/register"' in page
    assert "default-src 'self'" in client.get("/").headers["Content-Security-Policy"]


def test_valid_entry_is_stored_normalised_and_redirects(client, app):
    response = client.post("/register", data=VALID)
    assert response.status_code == 302 and response.headers["Location"].endswith("/thanks")
    assert entries(app) == [("Asha", "Rao", "9876543210", "asha@example.com")]
    assert "You're in, Asha!" in client.get("/thanks").get_data(as_text=True)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("mobile", "12345", "valid 10-digit"),
        ("mobile", "5876543210", "valid 10-digit"),  # Indian mobiles start with 6-9
        ("email", "not-an-email", "Invalid email"),
        ("first_name", "R2D2", "letters only"),
        ("consent", "", "accept the rules"),
    ],
)
def test_invalid_entries_are_rejected_with_messages(client, app, field, value, message):
    data = {**VALID, field: value}
    if field == "consent":
        data.pop("consent")
    response = client.post("/register", data=data)
    assert response.status_code == 400
    assert message in response.get_data(as_text=True)
    assert entries(app) == []


@pytest.mark.parametrize("mobile", ["09876543210", "919876543210", "98765-43210"])
def test_common_mobile_formats_are_accepted(client, app, mobile):
    assert client.post("/register", data={**VALID, "mobile": mobile}).status_code == 302
    assert entries(app)[0][2] == "9876543210"


def test_duplicates_by_email_or_mobile_are_refused(client, app):
    client.post("/register", data=VALID)
    same_email = client.post("/register", data={**VALID, "mobile": "9123456789", "email": "ASHA@example.com"})
    same_mobile = client.post("/register", data={**VALID, "email": "other@example.com", "mobile": "09876543210"})
    assert same_email.status_code == same_mobile.status_code == 409
    assert "already registered" in same_email.get_data(as_text=True)
    assert len(entries(app)) == 1


def test_honeypot_submissions_look_successful_but_are_not_stored(client, app):
    response = client.post("/register", data={**VALID, "website": "http://spam.example"})
    assert response.status_code == 302
    assert entries(app) == []


def test_user_input_is_escaped(client):
    page = client.post("/register", data={**VALID, "first_name": "<script>"}).get_data(as_text=True)
    assert "<script>" not in page.split("<form", 1)[1]


def test_csrf_is_enforced_when_enabled(tmp_path):
    client = create_app({"DATABASE": str(tmp_path / "c.sqlite3")}).test_client()
    assert client.post("/register", data=VALID).status_code == 400
    page = client.get("/register").get_data(as_text=True)
    token = re.search(r'name="csrf_token" type="hidden" value="([^"]+)"', page).group(1)
    assert client.post("/register", data={**VALID, "csrf_token": token}).status_code == 302


def test_admin_export_needs_the_token_and_neutralises_formulas(client, app):
    client.post("/register", data={**VALID, "first_name": "Asha", "last_name": "Rao-Iyer"})
    import sqlite3

    with sqlite3.connect(app.config["DATABASE"]) as db:
        db.execute(
            "insert into entries (first_name, last_name, mobile, email) values (?, ?, ?, ?)",
            ("=HYPERLINK(1)", "x", "9000000000", "f@x.io"),
        )
    assert client.get("/admin/entries.csv").status_code == 404
    assert client.get("/admin/entries.csv", headers={"Authorization": "Bearer wrong"}).status_code == 404
    response = client.get("/admin/entries.csv", headers={"Authorization": "Bearer s3cret-token"})
    assert response.status_code == 200 and response.mimetype == "text/csv"
    rows = list(csv.DictReader(io.StringIO(response.get_data(as_text=True))))
    assert [r["first_name"] for r in rows] == ["Asha", "'=HYPERLINK(1)"]


def test_export_is_disabled_without_a_configured_token(tmp_path):
    client = create_app({"TESTING": True, "DATABASE": str(tmp_path / "n.sqlite3"), "ADMIN_TOKEN": ""}).test_client()
    assert client.get("/admin/entries.csv", headers={"Authorization": "Bearer "}).status_code == 404


def test_health(client):
    assert client.get("/healthz").get_json() == {"status": "ok"}
