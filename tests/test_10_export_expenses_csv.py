# tests/test_10_export_expenses_csv.py
#
# Spec: .claude/specs/10-export-expenses-csv.md — Export Expenses CSV
#
# Every behavior below is derived from the spec's "Definition of done" (DoD)
# checklist and "Rules for implementation" section, NOT from reading
# app.py's export_expenses() body or queries.py's get_expenses_for_export()
# body. Those files were only read for import names / signatures / endpoint
# names while writing this file.
#
# DoD -> test mapping is noted above each test.

import csv
import io
import os
import re
import tempfile

import pytest

# ---------------------------------------------------------------------------
# Point the app at a fresh temp-file DB BEFORE importing app, so that the
# import-time init_db()/seed_db() calls in app.py never touch the real
# spendly.db. This mirrors tests/test_06_date_filter_profile.py exactly.
# ---------------------------------------------------------------------------
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()

import database.db as _db_module  # noqa: E402

_db_module.DB_PATH = _tmp_db.name  # redirect all connections to the temp file

from app import app  # noqa: E402 — must come after the DB_PATH patch
from database.db import get_db, init_db  # noqa: E402

TEMPLATES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates"
)
PROFILE_TEMPLATE_PATH = os.path.join(TEMPLATES_DIR, "profile.html")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    """Fresh Flask test client backed by an isolated temp-file DB."""
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret"

    with app.test_client() as c:
        with app.app_context():
            init_db()
            conn = get_db()
            conn.execute("DELETE FROM expenses")
            conn.execute("DELETE FROM users")
            conn.commit()
            conn.close()
        yield c

    # Wipe DB state after each test for isolation between tests.
    with app.app_context():
        conn = get_db()
        conn.execute("DELETE FROM expenses")
        conn.execute("DELETE FROM users")
        conn.commit()
        conn.close()


# ---------------------------------------------------------------------------
# Helpers — built only from documented form fields / schema, per CLAUDE.md.
# Registration posts name/email/password/confirm_password; login posts
# email/password. There is no username field anywhere in Spendly.
# ---------------------------------------------------------------------------

def _register(c, name="Test User", email="test@spendly.com", password="password123"):
    return c.post(
        "/register",
        data={
            "name": name,
            "email": email,
            "password": password,
            "confirm_password": password,
        },
        follow_redirects=True,
    )


def _login(c, email="test@spendly.com", password="password123"):
    return c.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def _register_and_login(c, name="Test User", email="test@spendly.com", password="password123"):
    """Register + log in a fresh user, return their user_id."""
    _register(c, name=name, email=email, password=password)
    _login(c, email=email, password=password)
    with app.app_context():
        conn = get_db()
        row = conn.execute(
            "SELECT id FROM users WHERE email = ?", (email,)
        ).fetchone()
        conn.close()
    return row["id"]


def _insert_expense(user_id, amount, category, expense_date, description):
    """Insert a row directly into `expenses` via parameterized SQL.

    Bypasses the /expenses/add route so tests can control raw amount,
    date, and description values (including None) precisely.
    """
    with app.app_context():
        conn = get_db()
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, category, expense_date, description),
        )
        conn.commit()
        conn.close()


def _parse_csv(body_text):
    """Parse a CSV response body into a list of rows via csv.reader.

    Never string-split — that would silently break on embedded commas,
    quotes, or newlines inside quoted fields.
    """
    return list(csv.reader(io.StringIO(body_text)))


def _header_index(header_row, column_name):
    lowered = [h.lower() for h in header_row]
    return lowered.index(column_name)


# ---------------------------------------------------------------------------
# DoD 1 — auth guard: logged-out GET redirects to /login, no CSV body
# ---------------------------------------------------------------------------

class TestAuthGuard:
    def test_export_logged_out_returns_302_to_login(self, client):
        response = client.get("/expenses/export", follow_redirects=False)
        assert response.status_code == 302, "Logged-out export must redirect, not serve a file"
        assert "/login" in response.headers["Location"]

    def test_export_logged_out_does_not_return_csv_content_type(self, client):
        response = client.get("/expenses/export", follow_redirects=False)
        content_type = response.headers.get("Content-Type", "")
        assert "text/csv" not in content_type, "Logged-out response must not be a CSV body"


# ---------------------------------------------------------------------------
# DoD 2 — logged-in export: 200, Content-Type text/csv, attachment .csv filename
# ---------------------------------------------------------------------------

class TestSuccessResponse:
    def test_export_logged_in_returns_200(self, client):
        user_id = _register_and_login(client)
        _insert_expense(user_id, 100.0, "Food", "2026-04-01", "Lunch")
        response = client.get("/expenses/export")
        assert response.status_code == 200

    def test_export_content_type_is_csv(self, client):
        user_id = _register_and_login(client)
        _insert_expense(user_id, 100.0, "Food", "2026-04-01", "Lunch")
        response = client.get("/expenses/export")
        assert "text/csv" in response.headers.get("Content-Type", "")

    def test_export_content_disposition_is_attachment_with_csv_filename(self, client):
        user_id = _register_and_login(client)
        _insert_expense(user_id, 100.0, "Food", "2026-04-01", "Lunch")
        response = client.get("/expenses/export")
        disposition = response.headers.get("Content-Disposition", "")
        assert "attachment" in disposition, "Must be served as a downloadable attachment"
        assert ".csv" in disposition, "Attachment filename must end in .csv"


# ---------------------------------------------------------------------------
# DoD 3 — header row names date/category/amount/description
# ---------------------------------------------------------------------------

class TestHeaderRow:
    def test_export_header_row_names_expected_columns(self, client):
        user_id = _register_and_login(client)
        _insert_expense(user_id, 100.0, "Food", "2026-04-01", "Lunch")
        response = client.get("/expenses/export")
        rows = _parse_csv(response.data.decode())
        header = [h.lower() for h in rows[0]]
        assert "date" in header
        assert "category" in header
        assert "amount" in header
        assert "description" in header


# ---------------------------------------------------------------------------
# DoD 4 — raw values, not display strings (no thousands comma, ISO dates)
# ---------------------------------------------------------------------------

class TestRawValues:
    def test_export_amount_has_no_thousands_comma(self, client):
        user_id = _register_and_login(client)
        _insert_expense(user_id, 1200.0, "Shopping", "2026-04-03", "Big purchase")
        response = client.get("/expenses/export")
        body = response.data.decode()
        assert "1,200.00" not in body, "Amount must be a raw number, not a display string"

    def test_export_date_is_iso_not_display_format(self, client):
        user_id = _register_and_login(client)
        _insert_expense(user_id, 1200.0, "Shopping", "2026-04-03", "Big purchase")
        response = client.get("/expenses/export")
        body = response.data.decode()
        assert "03 Apr 2026" not in body, "Date must be ISO, not the profile's display format"

    def test_export_row_values_are_raw_amount_and_iso_date(self, client):
        user_id = _register_and_login(client)
        _insert_expense(user_id, 1200.0, "Shopping", "2026-04-03", "Big purchase")
        response = client.get("/expenses/export")
        rows = _parse_csv(response.data.decode())
        header, data_row = rows[0], rows[1]
        date_idx = _header_index(header, "date")
        amount_idx = _header_index(header, "amount")
        assert data_row[date_idx] == "2026-04-03"
        assert float(data_row[amount_idx]) == 1200.0


# ---------------------------------------------------------------------------
# DoD 5 — more than 10 expenses returns ALL of them (no inherited limit=10)
# ---------------------------------------------------------------------------

class TestNoRowLimit:
    def test_export_more_than_ten_expenses_returns_all_rows(self, client):
        user_id = _register_and_login(client)
        for i in range(15):
            _insert_expense(
                user_id, 10.0 + i, "Other", f"2026-01-{i + 1:02d}", f"Item {i}"
            )
        response = client.get("/expenses/export")
        rows = _parse_csv(response.data.decode())
        data_rows = rows[1:]
        assert len(data_rows) == 15, (
            "Export must not inherit get_recent_transactions()'s limit=10"
        )


# ---------------------------------------------------------------------------
# DoD 6 — cross-user isolation: user A never sees user B's rows
# ---------------------------------------------------------------------------

class TestCrossUserIsolation:
    def test_export_excludes_other_users_expenses(self, client):
        user_a_id = _register_and_login(client, email="alice@spendly.com")
        _insert_expense(user_a_id, 50.0, "Food", "2026-04-01", "Alice lunch")
        client.get("/logout", follow_redirects=True)

        user_b_id = _register_and_login(client, email="bob@spendly.com")
        _insert_expense(user_b_id, 75.0, "Food", "2026-04-01", "Bob lunch")

        response = client.get("/expenses/export")  # as user B
        body = response.data.decode()
        assert "Bob lunch" in body
        assert "Alice lunch" not in body, "user_id must scope the SQL, never filtered in Python"


# ---------------------------------------------------------------------------
# DoD 7 — date range filtering; export and profile agree on a <=10-row range
#
# NOTE: set-equality with /profile is only asserted here because this range
# is 3 rows. get_recent_transactions() caps the profile table at limit=10,
# so a >10-row range would make export and profile legitimately disagree —
# that scenario is covered by DoD 5 against the export alone, not here.
# ---------------------------------------------------------------------------

class TestDateRangeFiltering:
    def test_export_date_range_returns_only_rows_in_range(self, client):
        user_id = _register_and_login(client)
        _insert_expense(user_id, 10.0, "Food", "2026-04-01", "In range 1")
        _insert_expense(user_id, 20.0, "Food", "2026-04-02", "In range 2")
        _insert_expense(user_id, 30.0, "Food", "2026-04-03", "In range 3")
        _insert_expense(user_id, 40.0, "Food", "2026-04-10", "Out of range")

        response = client.get("/expenses/export?date_from=2026-04-01&date_to=2026-04-03")
        body = response.data.decode()
        assert "In range 1" in body
        assert "In range 2" in body
        assert "In range 3" in body
        assert "Out of range" not in body

    def test_export_date_range_matches_profile_same_range(self, client):
        user_id = _register_and_login(client)
        _insert_expense(user_id, 10.0, "Food", "2026-04-01", "In range 1")
        _insert_expense(user_id, 20.0, "Food", "2026-04-02", "In range 2")
        _insert_expense(user_id, 30.0, "Food", "2026-04-03", "In range 3")
        _insert_expense(user_id, 40.0, "Food", "2026-04-10", "Out of range")

        export_body = client.get(
            "/expenses/export?date_from=2026-04-01&date_to=2026-04-03"
        ).data.decode()
        profile_body = client.get(
            "/profile?date_from=2026-04-01&date_to=2026-04-03"
        ).data.decode()

        for description in ("In range 1", "In range 2", "In range 3"):
            assert description in export_body
            assert description in profile_body
        assert "Out of range" not in export_body
        assert "Out of range" not in profile_body


# ---------------------------------------------------------------------------
# DoD 8 — only date_from (no date_to) returns all rows, no error
# ---------------------------------------------------------------------------

class TestOneSidedDateFilter:
    def test_export_only_date_from_returns_all_rows_without_error(self, client):
        user_id = _register_and_login(client)
        _insert_expense(user_id, 10.0, "Food", "2026-01-01", "Old row")
        _insert_expense(user_id, 20.0, "Food", "2026-06-01", "New row")

        response = client.get("/expenses/export?date_from=2026-04-01")
        assert response.status_code == 200
        body = response.data.decode()
        assert "Old row" in body
        assert "New row" in body

    def test_export_only_date_to_returns_all_rows_without_error(self, client):
        user_id = _register_and_login(client)
        _insert_expense(user_id, 10.0, "Food", "2026-01-01", "Old row")
        _insert_expense(user_id, 20.0, "Food", "2026-06-01", "New row")

        response = client.get("/expenses/export?date_to=2026-04-01")
        assert response.status_code == 200
        body = response.data.decode()
        assert "Old row" in body
        assert "New row" in body


# ---------------------------------------------------------------------------
# DoD 9 — invalid date string returns 200 with all rows, not a 500
# ---------------------------------------------------------------------------

class TestInvalidDateHandling:
    def test_export_invalid_date_from_returns_200_not_500(self, client):
        user_id = _register_and_login(client)
        _insert_expense(user_id, 10.0, "Food", "2026-01-01", "Row1")

        response = client.get("/expenses/export?date_from=not-a-date")
        assert response.status_code == 200
        assert "Row1" in response.data.decode()

    @pytest.mark.parametrize("bad_date", [
        "not-a-date",
        "2026/04/01",
        "20260401",
        "",
        "null",
    ])
    def test_export_various_malformed_date_from_values_do_not_crash(self, client, bad_date):
        user_id = _register_and_login(client)
        _insert_expense(user_id, 10.0, "Food", "2026-01-01", "Row1")

        response = client.get(f"/expenses/export?date_from={bad_date}")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# DoD 10 — empty description produces an empty CSV field, not the text "None"
# ---------------------------------------------------------------------------

class TestEmptyDescription:
    def test_export_null_description_is_empty_field_not_none_text(self, client):
        user_id = _register_and_login(client)
        _insert_expense(user_id, 10.0, "Food", "2026-01-01", None)

        response = client.get("/expenses/export")
        rows = _parse_csv(response.data.decode())
        header, data_row = rows[0], rows[1]
        desc_idx = _header_index(header, "description")
        assert data_row[desc_idx] == "", "NULL description must serialise to an empty field"
        assert "None" not in response.data.decode()


# ---------------------------------------------------------------------------
# DoD 11 — zero expenses gets a 200 with only the header row
# ---------------------------------------------------------------------------

class TestZeroExpenses:
    def test_export_with_no_expenses_returns_header_row_only(self, client):
        _register_and_login(client)
        response = client.get("/expenses/export")
        assert response.status_code == 200
        rows = _parse_csv(response.data.decode())
        assert len(rows) == 1, "Only the header row should be present when there are no expenses"


# ---------------------------------------------------------------------------
# DoD 12 — profile page renders the export link with the active filter,
# and the template source never hardcodes the /expenses/export path
# ---------------------------------------------------------------------------

class TestProfileExportLink:
    def test_profile_export_link_present_with_no_filter(self, client):
        _register_and_login(client)
        body = client.get("/profile").data.decode()
        assert re.search(r'href="[^"]*expenses/export[^"]*"', body), "Export link must be present"

    def test_profile_export_link_carries_active_date_filter(self, client):
        _register_and_login(client)
        body = client.get(
            "/profile?date_from=2026-04-01&date_to=2026-04-03"
        ).data.decode()
        match = re.search(r'href="([^"]*expenses/export[^"]*)"', body)
        assert match, "Export link not found in filtered profile page"
        href = match.group(1)
        assert "date_from=2026-04-01" in href
        assert "date_to=2026-04-03" in href

    def test_profile_template_source_has_no_hardcoded_export_path(self):
        with open(PROFILE_TEMPLATE_PATH, "r", encoding="utf-8") as f:
            source = f.read()
        assert (
            "url_for('export_expenses'" in source
            or 'url_for("export_expenses"' in source
        ), "Template must build the export link via url_for(), not a literal path"
        assert 'href="/expenses/export' not in source, "Path must never be hardcoded"
        assert "href='/expenses/export" not in source, "Path must never be hardcoded"


# ---------------------------------------------------------------------------
# Edge cases implied by the spec's rules (csv.writer/io.StringIO, one-sided
# _build_date_filter no-op, order validation only on /profile not /export)
# ---------------------------------------------------------------------------

class TestSpecialCharacterRoundTrip:
    def test_description_with_comma_quote_and_newline_round_trips(self, client):
        user_id = _register_and_login(client)
        tricky_description = 'Lunch, "extra" cheese\nand fries'
        _insert_expense(user_id, 15.0, "Food", "2026-04-01", tricky_description)

        response = client.get("/expenses/export")
        rows = _parse_csv(response.data.decode())
        header, data_row = rows[0], rows[1]
        desc_idx = _header_index(header, "description")
        assert data_row[desc_idx] == tricky_description, (
            "csv.writer/csv.reader must round-trip commas, quotes, and "
            "newlines intact — never string-split the response body"
        )


class TestDateRangeOrdering:
    def test_inverted_date_range_does_not_error(self, client):
        """date_from > date_to must not crash the export (unlike /profile,
        which flashes a validation error, this route has no such rule
        documented — only that it must not error)."""
        user_id = _register_and_login(client)
        _insert_expense(user_id, 10.0, "Food", "2026-04-01", "Row1")

        response = client.get(
            "/expenses/export?date_from=2026-12-31&date_to=2026-01-01"
        )
        assert response.status_code == 200

    def test_date_from_equal_to_date_to_returns_single_day_rows(self, client):
        user_id = _register_and_login(client)
        _insert_expense(user_id, 10.0, "Food", "2026-04-01", "Day one")
        _insert_expense(user_id, 20.0, "Food", "2026-04-02", "Day two")

        response = client.get(
            "/expenses/export?date_from=2026-04-01&date_to=2026-04-01"
        )
        body = response.data.decode()
        assert "Day one" in body
        assert "Day two" not in body
