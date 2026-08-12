"""
Tests for Step 9: Delete Expense feature
Spec: .claude/specs/09-delete-expense.md

Covers:
- POST /expenses/<id>/delete auth guard (unauthenticated → 302 /login, row remains)
- GET /expenses/<id>/delete → 405 (method not allowed)
- POST /expenses/<id>/delete authenticated, own expense → 302 /profile, row gone
- POST /expenses/<id>/delete authenticated, other user's expense → 404, row remains
- POST /expenses/<id>/delete authenticated, non-existent id → 404
- Profile page renders a delete <form> for each transaction row
- Unit: delete_expense_by_id() removes only the matching (id, user_id) row
- Unit: delete_expense_by_id() silently no-ops on wrong user / non-existent id
"""

import pytest
from werkzeug.security import generate_password_hash

import database.db as db_module
from app import app as flask_app
from database.db import init_db
from database.queries import delete_expense_by_id

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_spendly.db")


@pytest.fixture
def app(db_path, monkeypatch):
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
    conn = db_module.get_db()
    row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return row["id"], email, password


@pytest.fixture
def auth_client(client, registered_user):
    user_id, _email, _password = registered_user
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_name"] = "Test User"
    return client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_user(name, email):
    conn = db_module.get_db()
    cursor = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        (name, email, generate_password_hash("pass")),
    )
    conn.commit()
    user_id = cursor.lastrowid
    conn.close()
    return user_id


def _create_expense(
    user_id, amount=50.0, category="Food", date="2026-03-20", description="Lunch"
):
    conn = db_module.get_db()
    cursor = conn.execute(
        "INSERT INTO expenses (user_id, amount, category, date, description) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, amount, category, date, description),
    )
    conn.commit()
    expense_id = cursor.lastrowid
    conn.close()
    return expense_id


def _get_expense(expense_id):
    conn = db_module.get_db()
    row = conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
    conn.close()
    return row


# ===========================================================================
# Unit tests for delete_expense_by_id()
# ===========================================================================


class TestDeleteExpenseByIdUnit:
    def test_correct_user_removes_row(self, app):
        user_id = _create_user("Owner", "owner@example.com")
        expense_id = _create_expense(user_id)

        delete_expense_by_id(expense_id, user_id)

        assert (
            _get_expense(expense_id) is None
        ), "Row should be removed when called with correct user_id"

    def test_wrong_user_leaves_row_intact(self, app):
        owner_id = _create_user("Owner", "owner@example.com")
        other_id = _create_user("Other", "other@example.com")
        expense_id = _create_expense(owner_id)

        delete_expense_by_id(expense_id, other_id)

        row = _get_expense(expense_id)
        assert (
            row is not None
        ), "Row should not be deleted when called with wrong user_id"
        assert row["user_id"] == owner_id, "Ownership should be unchanged"

    def test_nonexistent_id_does_not_raise(self, app):
        user_id = _create_user("Owner", "owner@example.com")
        _create_expense(user_id)

        # Should silently no-op — no exception
        delete_expense_by_id(99999, user_id)

    def test_only_target_row_removed(self, app):
        user_id = _create_user("Owner", "owner@example.com")
        keep_id = _create_expense(user_id, amount=10.0, description="Keep")
        delete_id = _create_expense(user_id, amount=20.0, description="Delete")

        delete_expense_by_id(delete_id, user_id)

        assert _get_expense(delete_id) is None
        assert (
            _get_expense(keep_id) is not None
        ), "Other rows belonging to the same user must not be affected"


# ===========================================================================
# Route: POST /expenses/<id>/delete — auth guard
# ===========================================================================


class TestDeleteRouteAuthGuard:
    def test_unauthenticated_post_redirects_to_login(self, client, app):
        user_id = _create_user("Owner", "owner@example.com")
        expense_id = _create_expense(user_id)

        response = client.post(f"/expenses/{expense_id}/delete")

        assert response.status_code == 302, "Unauthenticated POST should redirect (302)"
        assert (
            "/login" in response.headers["Location"]
        ), "Unauthenticated POST should redirect to /login"

    def test_unauthenticated_post_leaves_row_intact(self, client, app):
        user_id = _create_user("Owner", "owner@example.com")
        expense_id = _create_expense(user_id)

        client.post(f"/expenses/{expense_id}/delete")

        assert (
            _get_expense(expense_id) is not None
        ), "Unauthenticated POST must not delete the row"


# ===========================================================================
# Route: GET /expenses/<id>/delete — method not allowed
# ===========================================================================


class TestDeleteRouteMethodNotAllowed:
    def test_unauthenticated_get_returns_405(self, client, app):
        user_id = _create_user("Owner", "owner@example.com")
        expense_id = _create_expense(user_id)

        response = client.get(f"/expenses/{expense_id}/delete")

        assert (
            response.status_code == 405
        ), "GET on delete route should return 405 Method Not Allowed"

    def test_authenticated_get_returns_405(self, auth_client, registered_user):
        user_id, _email, _password = registered_user
        expense_id = _create_expense(user_id)

        response = auth_client.get(f"/expenses/{expense_id}/delete")

        assert (
            response.status_code == 405
        ), "GET on delete route should return 405 even when authenticated"

    def test_get_does_not_delete_row(self, auth_client, registered_user):
        user_id, _email, _password = registered_user
        expense_id = _create_expense(user_id)

        auth_client.get(f"/expenses/{expense_id}/delete")

        assert (
            _get_expense(expense_id) is not None
        ), "GET on delete route must not delete the row"


# ===========================================================================
# Route: POST /expenses/<id>/delete — happy path
# ===========================================================================


class TestDeleteRouteHappyPath:
    def test_authenticated_own_expense_redirects_to_profile(
        self, auth_client, registered_user
    ):
        user_id, _email, _password = registered_user
        expense_id = _create_expense(user_id)

        response = auth_client.post(f"/expenses/{expense_id}/delete")

        assert response.status_code == 302, "Successful delete should redirect (302)"
        assert (
            "/profile" in response.headers["Location"]
        ), "Successful delete should redirect to /profile"

    def test_authenticated_own_expense_removes_row(self, auth_client, registered_user):
        user_id, _email, _password = registered_user
        expense_id = _create_expense(user_id)

        auth_client.post(f"/expenses/{expense_id}/delete")

        assert (
            _get_expense(expense_id) is None
        ), "Row should be removed from DB after successful delete"


# ===========================================================================
# Route: POST /expenses/<id>/delete — ownership / existence
# ===========================================================================


class TestDeleteRouteOwnership:
    def test_other_users_expense_returns_404(self, auth_client, registered_user):
        _user_id, _email, _password = registered_user
        other_id = _create_user("Other", "other@example.com")
        expense_id = _create_expense(other_id)

        response = auth_client.post(f"/expenses/{expense_id}/delete")

        assert (
            response.status_code == 404
        ), "POST on another user's expense should return 404"

    def test_other_users_expense_leaves_row_intact(self, auth_client, registered_user):
        _user_id, _email, _password = registered_user
        other_id = _create_user("Other", "other@example.com")
        expense_id = _create_expense(other_id)

        auth_client.post(f"/expenses/{expense_id}/delete")

        assert (
            _get_expense(expense_id) is not None
        ), "Another user's expense must not be deleted"

    def test_nonexistent_id_returns_404(self, auth_client):
        response = auth_client.post("/expenses/99999/delete")

        assert (
            response.status_code == 404
        ), "POST on a non-existent expense id should return 404"


# ===========================================================================
# Profile template: delete form rendered per row
# ===========================================================================


class TestProfileDeleteFormRendered:
    def test_profile_contains_delete_form_for_each_expense(
        self, auth_client, registered_user
    ):
        user_id, _email, _password = registered_user
        expense_id = _create_expense(user_id)

        response = auth_client.get("/profile")
        body = response.data.decode()

        assert response.status_code == 200
        assert (
            f"/expenses/{expense_id}/delete" in body
        ), "Profile should render a form whose action targets the delete route"
        assert (
            'method="POST"' in body or "method='POST'" in body
        ), "The delete form should use POST"
        assert (
            ">Delete<" in body or ">Delete <" in body or "Delete</button>" in body
        ), "Profile should render a Delete button"

    def test_profile_delete_form_has_confirm_handler(
        self, auth_client, registered_user
    ):
        user_id, _email, _password = registered_user
        _create_expense(user_id)

        response = auth_client.get("/profile")
        body = response.data.decode()

        assert (
            "confirm(" in body
        ), "Delete form should attach a confirm() handler to guard accidental clicks"
