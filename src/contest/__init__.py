"""Contest sign-up microsite: landing page, validated registration, and an admin CSV export."""

from __future__ import annotations

import csv
import hmac
import io
import logging
import os
import secrets
import sqlite3
from pathlib import Path

from flask import Flask, Response, abort, current_app, flash, g, redirect, render_template, request, url_for
from flask_wtf import CSRFProtect

from .forms import EntryForm

log = logging.getLogger(__name__)
csrf = CSRFProtect()

SCHEMA = """
create table if not exists entries (
    id integer primary key autoincrement,
    first_name text not null,
    last_name text not null,
    mobile text not null unique,
    email text not null unique collate nocase,
    created_at text not null default (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
"""


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    secret = os.environ.get("SECRET_KEY")
    if not secret:
        log.warning("SECRET_KEY is not set: using a random key, so sessions reset on restart")
        secret = secrets.token_hex(32)
    app.config.update(
        SECRET_KEY=secret,
        DATABASE=os.environ.get("DATABASE_PATH", str(Path(app.instance_path) / "entries.sqlite3")),
        ADMIN_TOKEN=os.environ.get("ADMIN_TOKEN", ""),
        CONTEST_NAME=os.environ.get("CONTEST_NAME", "The Itchy Challenge"),
        BRAND_NAME=os.environ.get("BRAND_NAME", "Talcum Pros"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=16 * 1024,
    )
    app.config.update(config or {})
    csrf.init_app(app)
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(app.config["DATABASE"]) as db:
        db.executescript(SCHEMA)

    app.teardown_appcontext(_close_db)
    app.after_request(_security_headers)

    @app.context_processor
    def branding():
        return {"contest": app.config["CONTEST_NAME"], "brand": app.config["BRAND_NAME"]}

    @app.get("/")
    def home():
        return render_template("home.html")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        form = EntryForm()
        if form.validate_on_submit():
            if form.website.data:  # honeypot filled in: almost certainly a bot; pretend success
                return redirect(url_for("thanks"))
            try:
                with _db() as db:
                    db.execute(
                        "insert into entries (first_name, last_name, mobile, email) values (?, ?, ?, ?)",
                        (
                            form.first_name.data.strip(),
                            form.last_name.data.strip(),
                            form.normalised_mobile(),
                            form.email.data.strip().lower(),
                        ),
                    )
            except sqlite3.IntegrityError:
                form.email.errors.append("This email or mobile number is already registered.")
                return render_template("register.html", form=form), 409
            flash(form.first_name.data.strip())
            return redirect(url_for("thanks"))
        status = 400 if request.method == "POST" else 200
        return render_template("register.html", form=form), status

    @app.get("/thanks")
    def thanks():
        return render_template("thanks.html")

    @app.get("/admin/entries.csv")
    def export():
        expected = current_app.config["ADMIN_TOKEN"]
        supplied = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if not expected or not hmac.compare_digest(supplied, expected):
            abort(404)  # do not advertise that the endpoint exists
        rows = (
            _db()
            .execute("select id, first_name, last_name, mobile, email, created_at from entries order by id")
            .fetchall()
        )
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["id", "first_name", "last_name", "mobile", "email", "created_at"])
        writer.writerows([[_csv_safe(v) for v in row] for row in rows])
        return Response(
            out.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=entries.csv", "Cache-Control": "no-store"},
        )

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    return app


def _db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
    return g.db


def _close_db(_exc) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _csv_safe(value):
    """Neutralise spreadsheet formulas (CSV injection) in user-supplied text."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def _security_headers(response):
    response.headers.setdefault(
        "Content-Security-Policy", "default-src 'self'; style-src 'self'; img-src 'self'; frame-ancestors 'none'"
    )
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response
