"""
Tests for Step 7: Add Expense feature
Spec: .claude/specs/07-add-expense.md

Covers:
- GET /expenses/add auth guard (unauthenticated → 302 /login)
- GET /expenses/add authenticated → 200, form with all 7 categories, POST method
- POST /expenses/add auth guard (unauthenticated → 302 /login)
- POST /expenses/add valid data → 302 /profile, row in DB
- POST /expenses/add validation errors (missing amount, zero amount, non-numeric,
  invalid category, invalid date) → 200 + error message
- POST /expenses/add no description → 302 /profile, NULL description stored
- Unit: create_expense() inserts row with correct values
- Unit: create_expense() stores NULL when description=None
"""

import os
import sqlite3
import tempfile

import pytest

import database.db as db_module
from app import app as flask_app
from database.db import init_db
from database.queries import insert_expense as create_expense


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path):
    """Return the path to a fresh, isolated SQLite database file."""
    return str(tmp_path / "test_spendly.db")


@pytest.fixture
def app(db_path, monkeypatch):
    """
    Flask app configured for testing with an isolated SQLite DB.

    monkeypatch replaces DB_PATH in database.db so that every call to
    get_db() — whether from route handlers or helper functions — uses the
    temp database, never the real spendly.db.
    """
    monkeypatch.setattr(db_module, "DB_PATH", db_path)

    flask_app.config.update(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "WTF_CSRF_ENABLED": False,
        }
    )

    with flask_app.app_context():
        init_db()
        yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def registered_user(client):
    """
    Register a fresh test user and return (user_id, email, password).
    Registration goes through the route so the password is hashed properly.
    """
    email = "testuser@example.com"
    password = "testpass123"
    client.post(
        "/register",
        data={
            "name": "Test User",
            "email": email,
            "password": password,
            "confirm_password": password,
        },
        follow_redirects=True,
    )
    # Retrieve the user_id from the DB directly
    conn = db_module.get_db()
    row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    user_id = row["id"]
    return user_id, email, password


@pytest.fixture
def auth_client(client, registered_user):
    """A test client with a valid session already injected."""
    user_id, _email, _password = registered_user
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_name"] = "Test User"
    return client


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

VALID_CATEGORIES = [
    "Food",
    "Transport",
    "Bills",
    "Health",
    "Entertainment",
    "Shopping",
    "Other",
]


def _get_expenses_for_user(user_id):
    """Query the test DB directly and return all expense rows for user_id."""
    conn = db_module.get_db()
    rows = conn.execute(
        "SELECT * FROM expenses WHERE user_id = ?", (user_id,)
    ).fetchall()
    conn.close()
    return rows


# ===========================================================================
# GET /expenses/add
# ===========================================================================


class TestGetAddExpense:
    def test_unauthenticated_get_redirects_to_login(self, client):
        response = client.get("/expenses/add")
        assert response.status_code == 302, "Expected 302 redirect for unauthenticated GET"
        assert "/login" in response.headers["Location"], (
            "Unauthenticated GET /expenses/add should redirect to /login"
        )

    def test_authenticated_get_returns_200(self, auth_client):
        response = auth_client.get("/expenses/add")
        assert response.status_code == 200, "Authenticated GET /expenses/add should return 200"

    def test_authenticated_get_contains_form_with_post_method(self, auth_client):
        response = auth_client.get("/expenses/add")
        body = response.data.decode()
        assert "<form" in body.lower(), "Response should contain a <form> element"
        assert 'method="POST"' in body or "method='POST'" in body or "method=POST" in body.upper(), (
            "Form should use POST method"
        )

    def test_authenticated_get_contains_all_7_category_options(self, auth_client):
        response = auth_client.get("/expenses/add")
        body = response.data.decode()
        for category in VALID_CATEGORIES:
            assert category in body, (
                f"Category option '{category}' not found in the add-expense form"
            )

    def test_authenticated_get_contains_amount_field(self, auth_client):
        response = auth_client.get("/expenses/add")
        body = response.data.decode()
        assert 'name="amount"' in body, "Form should contain an amount input field"

    def test_authenticated_get_contains_date_field(self, auth_client):
        response = auth_client.get("/expenses/add")
        body = response.data.decode()
        assert 'name="date"' in body, "Form should contain a date input field"

    def test_authenticated_get_contains_description_field(self, auth_client):
        response = auth_client.get("/expenses/add")
        body = response.data.decode()
        assert 'name="description"' in body, "Form should contain a description field"

    def test_authenticated_get_contains_exactly_7_category_options(self, auth_client):
        response = auth_client.get("/expenses/add")
        body = response.data.decode()
        option_count = sum(1 for cat in VALID_CATEGORIES if cat in body)
        assert option_count == 7, (
            f"Expected exactly 7 category options, found {option_count}"
        )


# ===========================================================================
# POST /expenses/add — auth guard
# ===========================================================================


class TestPostAddExpenseAuthGuard:
    def test_unauthenticated_post_redirects_to_login(self, client):
        response = client.post(
            "/expenses/add",
            data={
                "amount": "50.0",
                "category": "Food",
                "date": "2026-03-20",
                "description": "Lunch",
            },
        )
        assert response.status_code == 302, "Expected 302 redirect for unauthenticated POST"
        assert "/login" in response.headers["Location"], (
            "Unauthenticated POST /expenses/add should redirect to /login"
        )


# ===========================================================================
# POST /expenses/add — happy path
# ===========================================================================


class TestPostAddExpenseHappyPath:
    def test_valid_post_redirects_to_profile(self, auth_client):
        response = auth_client.post(
            "/expenses/add",
            data={
                "amount": "50.0",
                "category": "Food",
                "date": "2026-03-20",
                "description": "Lunch",
            },
        )
        assert response.status_code == 302, "Valid POST should redirect (302)"
        assert "/profile" in response.headers["Location"], (
            "Valid POST should redirect to /profile"
        )

    def test_valid_post_inserts_row_in_db(self, auth_client, registered_user):
        user_id, _email, _password = registered_user
        auth_client.post(
            "/expenses/add",
            data={
                "amount": "50.0",
                "category": "Food",
                "date": "2026-03-20",
                "description": "Lunch",
            },
        )
        rows = _get_expenses_for_user(user_id)
        assert len(rows) == 1, "Expected exactly one expense row in DB after valid POST"
        row = rows[0]
        assert row["amount"] == 50.0, f"Expected amount 50.0, got {row['amount']}"
        assert row["category"] == "Food", f"Expected category 'Food', got {row['category']}"
        assert row["date"] == "2026-03-20", f"Expected date '2026-03-20', got {row['date']}"
        assert row["description"] == "Lunch", f"Expected description 'Lunch', got {row['description']}"
        assert row["user_id"] == user_id, "Expense should be linked to the correct user"

    def test_post_without_description_redirects_to_profile(self, auth_client):
        response = auth_client.post(
            "/expenses/add",
            data={
                "amount": "120.0",
                "category": "Transport",
                "date": "2026-03-21",
                "description": "",
            },
        )
        assert response.status_code == 302, "POST without description should redirect (302)"
        assert "/profile" in response.headers["Location"], (
            "POST without description should redirect to /profile"
        )

    def test_post_without_description_stores_null(self, auth_client, registered_user):
        user_id, _email, _password = registered_user
        auth_client.post(
            "/expenses/add",
            data={
                "amount": "120.0",
                "category": "Transport",
                "date": "2026-03-21",
                "description": "",
            },
        )
        rows = _get_expenses_for_user(user_id)
        assert len(rows) == 1, "Expected one expense row in DB"
        assert rows[0]["description"] is None, (
            "Empty description should be stored as NULL, not an empty string"
        )

    def test_post_with_whitespace_only_description_stores_null(self, auth_client, registered_user):
        user_id, _email, _password = registered_user
        auth_client.post(
            "/expenses/add",
            data={
                "amount": "75.5",
                "category": "Bills",
                "date": "2026-03-22",
                "description": "   ",
            },
        )
        rows = _get_expenses_for_user(user_id)
        assert len(rows) == 1, "Expected one expense row in DB"
        assert rows[0]["description"] is None, (
            "Whitespace-only description should be stored as NULL"
        )


# ===========================================================================
# POST /expenses/add — validation errors
# ===========================================================================


class TestPostAddExpenseValidation:
    def test_missing_amount_returns_200(self, auth_client):
        response = auth_client.post(
            "/expenses/add",
            data={
                "amount": "",
                "category": "Food",
                "date": "2026-03-20",
                "description": "Lunch",
            },
        )
        assert response.status_code == 200, (
            "Missing amount should re-render form with 200, not redirect"
        )

    def test_missing_amount_shows_error_message(self, auth_client):
        response = auth_client.post(
            "/expenses/add",
            data={
                "amount": "",
                "category": "Food",
                "date": "2026-03-20",
                "description": "Lunch",
            },
        )
        body = response.data.decode()
        # The spec requires an error message be displayed on the form
        assert any(
            phrase in body.lower()
            for phrase in ["amount", "positive", "required", "error", "invalid"]
        ), "Response should contain an error message when amount is missing"

    def test_zero_amount_returns_200(self, auth_client):
        response = auth_client.post(
            "/expenses/add",
            data={
                "amount": "0",
                "category": "Food",
                "date": "2026-03-20",
                "description": "Lunch",
            },
        )
        assert response.status_code == 200, (
            "Amount=0 should re-render form with 200, not redirect"
        )

    def test_zero_amount_shows_error_message(self, auth_client):
        response = auth_client.post(
            "/expenses/add",
            data={
                "amount": "0",
                "category": "Food",
                "date": "2026-03-20",
                "description": "Lunch",
            },
        )
        body = response.data.decode()
        assert any(
            phrase in body.lower()
            for phrase in ["amount", "positive", "greater", "error", "invalid"]
        ), "Response should contain an error message when amount is 0"

    def test_zero_amount_does_not_insert_row(self, auth_client, registered_user):
        user_id, _email, _password = registered_user
        auth_client.post(
            "/expenses/add",
            data={
                "amount": "0",
                "category": "Food",
                "date": "2026-03-20",
                "description": "Lunch",
            },
        )
        rows = _get_expenses_for_user(user_id)
        assert len(rows) == 0, "No row should be inserted when amount is 0"

    def test_negative_amount_returns_200(self, auth_client):
        response = auth_client.post(
            "/expenses/add",
            data={
                "amount": "-10",
                "category": "Food",
                "date": "2026-03-20",
                "description": "Lunch",
            },
        )
        assert response.status_code == 200, (
            "Negative amount should re-render form with 200, not redirect"
        )

    def test_non_numeric_amount_returns_200(self, auth_client):
        response = auth_client.post(
            "/expenses/add",
            data={
                "amount": "abc",
                "category": "Food",
                "date": "2026-03-20",
                "description": "Lunch",
            },
        )
        assert response.status_code == 200, (
            "Non-numeric amount should re-render form with 200, not redirect"
        )

    def test_non_numeric_amount_shows_error_message(self, auth_client):
        response = auth_client.post(
            "/expenses/add",
            data={
                "amount": "abc",
                "category": "Food",
                "date": "2026-03-20",
                "description": "Lunch",
            },
        )
        body = response.data.decode()
        assert any(
            phrase in body.lower()
            for phrase in ["amount", "positive", "number", "error", "invalid"]
        ), "Response should contain an error message for non-numeric amount"

    def test_non_numeric_amount_does_not_insert_row(self, auth_client, registered_user):
        user_id, _email, _password = registered_user
        auth_client.post(
            "/expenses/add",
            data={
                "amount": "abc",
                "category": "Food",
                "date": "2026-03-20",
                "description": "Lunch",
            },
        )
        rows = _get_expenses_for_user(user_id)
        assert len(rows) == 0, "No row should be inserted for non-numeric amount"

    def test_invalid_category_returns_200(self, auth_client):
        response = auth_client.post(
            "/expenses/add",
            data={
                "amount": "50.0",
                "category": "NotACategory",
                "date": "2026-03-20",
                "description": "Lunch",
            },
        )
        assert response.status_code == 200, (
            "Invalid category should re-render form with 200, not redirect"
        )

    def test_invalid_category_shows_error_message(self, auth_client):
        response = auth_client.post(
            "/expenses/add",
            data={
                "amount": "50.0",
                "category": "NotACategory",
                "date": "2026-03-20",
                "description": "Lunch",
            },
        )
        body = response.data.decode()
        assert any(
            phrase in body.lower()
            for phrase in ["category", "valid", "error", "invalid", "select"]
        ), "Response should contain an error message for invalid category"

    def test_invalid_category_does_not_insert_row(self, auth_client, registered_user):
        user_id, _email, _password = registered_user
        auth_client.post(
            "/expenses/add",
            data={
                "amount": "50.0",
                "category": "NotACategory",
                "date": "2026-03-20",
                "description": "Lunch",
            },
        )
        rows = _get_expenses_for_user(user_id)
        assert len(rows) == 0, "No row should be inserted for invalid category"

    def test_empty_category_returns_200(self, auth_client):
        response = auth_client.post(
            "/expenses/add",
            data={
                "amount": "50.0",
                "category": "",
                "date": "2026-03-20",
                "description": "Lunch",
            },
        )
        assert response.status_code == 200, (
            "Empty category should re-render form with 200, not redirect"
        )

    def test_invalid_date_returns_200(self, auth_client):
        response = auth_client.post(
            "/expenses/add",
            data={
                "amount": "50.0",
                "category": "Food",
                "date": "not-a-date",
                "description": "Lunch",
            },
        )
        assert response.status_code == 200, (
            "Invalid date should re-render form with 200, not redirect"
        )

    def test_invalid_date_shows_error_message(self, auth_client):
        response = auth_client.post(
            "/expenses/add",
            data={
                "amount": "50.0",
                "category": "Food",
                "date": "not-a-date",
                "description": "Lunch",
            },
        )
        body = response.data.decode()
        assert any(
            phrase in body.lower()
            for phrase in ["date", "valid", "error", "invalid"]
        ), "Response should contain an error message for invalid date"

    def test_invalid_date_does_not_insert_row(self, auth_client, registered_user):
        user_id, _email, _password = registered_user
        auth_client.post(
            "/expenses/add",
            data={
                "amount": "50.0",
                "category": "Food",
                "date": "not-a-date",
                "description": "Lunch",
            },
        )
        rows = _get_expenses_for_user(user_id)
        assert len(rows) == 0, "No row should be inserted for invalid date"

    def test_missing_date_returns_200(self, auth_client):
        response = auth_client.post(
            "/expenses/add",
            data={
                "amount": "50.0",
                "category": "Food",
                "date": "",
                "description": "Lunch",
            },
        )
        assert response.status_code == 200, (
            "Missing date should re-render form with 200, not redirect"
        )

    def test_wrong_date_format_returns_200(self, auth_client):
        """Date in DD/MM/YYYY format instead of required YYYY-MM-DD."""
        response = auth_client.post(
            "/expenses/add",
            data={
                "amount": "50.0",
                "category": "Food",
                "date": "20/03/2026",
                "description": "Lunch",
            },
        )
        assert response.status_code == 200, (
            "Date in wrong format should re-render form with 200, not redirect"
        )

    def test_validation_error_repopulates_amount(self, auth_client):
        """After a validation error, previously entered amount should be pre-filled."""
        response = auth_client.post(
            "/expenses/add",
            data={
                "amount": "99.99",
                "category": "NotACategory",
                "date": "2026-03-20",
                "description": "Test repopulation",
            },
        )
        body = response.data.decode()
        assert "99.99" in body, (
            "Previously entered amount should be pre-filled in the re-rendered form"
        )

    def test_validation_error_repopulates_description(self, auth_client):
        """After a validation error, previously entered description should be pre-filled."""
        response = auth_client.post(
            "/expenses/add",
            data={
                "amount": "50.0",
                "category": "Food",
                "date": "bad-date",
                "description": "My unique description text",
            },
        )
        body = response.data.decode()
        assert "My unique description text" in body, (
            "Previously entered description should appear in the re-rendered form"
        )


# ===========================================================================
# Parametrized: all valid categories succeed
# ===========================================================================


@pytest.mark.parametrize("category", VALID_CATEGORIES)
def test_each_valid_category_is_accepted(auth_client, registered_user, category):
    """Each of the 7 categories must be accepted and result in a redirect to /profile."""
    response = auth_client.post(
        "/expenses/add",
        data={
            "amount": "10.0",
            "category": category,
            "date": "2026-03-20",
            "description": f"Test {category}",
        },
    )
    assert response.status_code == 302, (
        f"Category '{category}' should be accepted; expected 302 redirect"
    )
    assert "/profile" in response.headers["Location"], (
        f"Category '{category}' POST should redirect to /profile"
    )


# ===========================================================================
# Unit tests for create_expense() in database/db.py
# ===========================================================================


class TestCreateExpenseUnit:
    """
    Unit tests for the create_expense() helper.
    These tests operate directly on the DB via db_module.get_db(),
    which is already patched to a temp path by the `app` fixture.
    """

    def _create_test_user(self):
        """Insert a bare user directly for unit-test isolation."""
        from werkzeug.security import generate_password_hash
        conn = db_module.get_db()
        cursor = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Unit User", "unit@example.com", generate_password_hash("pass")),
        )
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()
        return user_id

    def test_create_expense_inserts_row(self, app):
        user_id = self._create_test_user()
        expense_id = create_expense(user_id, 50.0, "Food", "2026-03-20", "Lunch")
        assert expense_id is not None, "create_expense should return the new row id"

        conn = db_module.get_db()
        row = conn.execute(
            "SELECT * FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        conn.close()

        assert row is not None, "A row should exist in expenses after create_expense"
        assert row["user_id"] == user_id, "user_id should match"
        assert row["amount"] == 50.0, "amount should be 50.0"
        assert row["category"] == "Food", "category should be 'Food'"
        assert row["date"] == "2026-03-20", "date should be '2026-03-20'"
        assert row["description"] == "Lunch", "description should be 'Lunch'"

    def test_create_expense_with_none_description_stores_null(self, app):
        user_id = self._create_test_user()
        expense_id = create_expense(user_id, 50.0, "Food", "2026-03-20", None)
        assert expense_id is not None, "create_expense should return the new row id"

        conn = db_module.get_db()
        row = conn.execute(
            "SELECT * FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        conn.close()

        assert row is not None, "Row should exist in expenses"
        assert row["description"] is None, (
            "description=None should be stored as SQL NULL, not the string 'None'"
        )

    def test_create_expense_returns_integer_id(self, app):
        user_id = self._create_test_user()
        expense_id = create_expense(user_id, 100.0, "Transport", "2026-04-01", "Bus")
        assert isinstance(expense_id, int), (
            "create_expense should return an integer row id"
        )
        assert expense_id > 0, "Returned id should be a positive integer"

    def test_create_expense_multiple_rows_have_unique_ids(self, app):
        user_id = self._create_test_user()
        id1 = create_expense(user_id, 10.0, "Food", "2026-03-20", "First")
        id2 = create_expense(user_id, 20.0, "Food", "2026-03-21", "Second")
        assert id1 != id2, "Each call to create_expense should produce a unique id"

    def test_create_expense_amount_stored_as_float(self, app):
        user_id = self._create_test_user()
        expense_id = create_expense(user_id, 99.99, "Bills", "2026-03-20", "Electric")

        conn = db_module.get_db()
        row = conn.execute(
            "SELECT amount FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        conn.close()

        assert abs(row["amount"] - 99.99) < 0.001, (
            "Amount should be stored and retrieved as a float with correct precision"
        )
