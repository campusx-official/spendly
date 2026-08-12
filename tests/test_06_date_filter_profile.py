# tests/test_06_date_filter_profile.py
#
# Spec: Step 6 — Date Filter for Profile Page
#
# Behaviors under test (all derived from the spec, not the implementation):
#
#  1. Auth guard: unauthenticated GET /profile redirects to /login
#  2. No filter params → HTTP 200, all expenses shown, "All Time" button active
#  3. "This Month" preset: filter scopes data to current calendar month
#  4. "Last 3 Months" preset: data scoped to 3-month window ending today
#  5. "Last 6 Months" preset: data scoped to 6-month window ending today
#  6. "All Time" (clean URL with no params) behaves identically to no-filter
#  7. Custom valid range: only expenses within date_from..date_to appear
#  8. Invalid order (date_from > date_to): flash error + unfiltered fallback
#  9. Malformed date string: no crash, unfiltered fallback (HTTP 200)
# 10. Empty period: "No expenses found for this period." in body, ₹0.00 / 0 / "—"
# 11. ₹ symbol always present in rendered amounts regardless of active filter
# 12. Query helper signatures: get_summary_stats, get_recent_transactions,
#     get_category_breakdown accept date_from/date_to kwargs and filter correctly

import os
import sqlite3
import tempfile
from datetime import date, timedelta

import pytest
from werkzeug.security import generate_password_hash

# ---------------------------------------------------------------------------
# Point the app at a fresh temp file DB before importing app so that
# init_db() and seed_db() do not pollute a shared on-disk file.
# ---------------------------------------------------------------------------
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["SPENDLY_TEST_DB"] = _tmp_db.name  # consumed below if db.py honours it

# Import after env is set so module-level side effects see the env var.
# We patch DB_PATH directly to guarantee isolation regardless of whether
# the app reads the env var.
import database.db as _db_module

_db_module.DB_PATH = _tmp_db.name  # redirect all connections to temp file

from app import app  # noqa: E402 — must come after path patch
from database.db import get_db, init_db
from database.queries import (  # noqa: E402
    get_category_breakdown,
    get_recent_transactions,
    get_summary_stats,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TODAY = date.today()
TODAY_STR = TODAY.isoformat()

# "This Month" preset boundaries
THIS_MONTH_FROM = TODAY.replace(day=1).isoformat()
import calendar as _calendar
THIS_MONTH_TO = TODAY.replace(
    day=_calendar.monthrange(TODAY.year, TODAY.month)[1]
).isoformat()

# "Last 3 Months" — first day of the month 3 months ago
def _months_ago_first(n: int) -> str:
    m, y = TODAY.month - n, TODAY.year
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1).isoformat()

LAST_3_FROM = _months_ago_first(3)
LAST_6_FROM = _months_ago_first(6)

# Fixed dates used to build seed data that spans multiple months.
# We construct expenses relative to TODAY so the tests remain valid regardless
# of when they run.
# Expense A: first day of current month → always inside "This Month"
EXPENSE_DATE_CURRENT_MONTH = TODAY.replace(day=1).isoformat()
# Expense B: first day 4 months ago → inside "Last 6 Months" but outside "This Month"
def _fixed_date_months_ago(n: int) -> str:
    m, y = TODAY.month - n, TODAY.year
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1).isoformat()

EXPENSE_DATE_OLD = _fixed_date_months_ago(4)   # 4 months ago → in last-6 but not last-3 unless edge
EXPENSE_DATE_ANCIENT = _fixed_date_months_ago(8)  # 8 months ago → only in "All Time"


def _setup_db():
    """Create tables and insert a test user plus a known set of expenses."""
    init_db()
    conn = get_db()

    # Remove any leftover data from previous test run
    conn.execute("DELETE FROM expenses")
    conn.execute("DELETE FROM users")
    conn.commit()

    cursor = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Test User", "test@spendly.com", generate_password_hash("password123")),
    )
    user_id = cursor.lastrowid

    expenses = [
        # Current month expenses
        (user_id, 500.00,  "Food",          EXPENSE_DATE_CURRENT_MONTH, "Groceries this month"),
        (user_id, 200.00,  "Transport",     EXPENSE_DATE_CURRENT_MONTH, "Metro this month"),
        # 4-months-ago expenses
        (user_id, 1000.00, "Bills",         EXPENSE_DATE_OLD, "Old electricity bill"),
        # 8-months-ago expenses (only in All Time)
        (user_id, 750.00,  "Shopping",      EXPENSE_DATE_ANCIENT, "Ancient shopping"),
    ]
    conn.executemany(
        "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
        expenses,
    )
    conn.commit()
    conn.close()
    return user_id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    """Fresh Flask test client backed by an isolated temp-file DB."""
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.test_client() as c:
        with app.app_context():
            user_id = _setup_db()
        yield c, user_id

    # Wipe DB state after each test for isolation
    with app.app_context():
        conn = get_db()
        conn.execute("DELETE FROM expenses")
        conn.execute("DELETE FROM users")
        conn.commit()
        conn.close()


def _login(c, email="test@spendly.com", password="password123"):
    """POST to /login and follow the redirect."""
    return c.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


# ---------------------------------------------------------------------------
# 1. Auth Guard
# ---------------------------------------------------------------------------

class TestAuthGuard:
    def test_unauthenticated_get_profile_redirects_to_login(self, client):
        c, _ = client
        response = c.get("/profile", follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_unauthenticated_get_profile_with_filter_params_redirects_to_login(self, client):
        c, _ = client
        response = c.get(
            f"/profile?date_from={THIS_MONTH_FROM}&date_to={THIS_MONTH_TO}",
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]


# ---------------------------------------------------------------------------
# 2. No filter — All Time unfiltered view
# ---------------------------------------------------------------------------

class TestNoFilter:
    def test_no_filter_returns_200(self, client):
        c, _ = client
        _login(c)
        response = c.get("/profile")
        assert response.status_code == 200

    def test_no_filter_shows_all_expenses(self, client):
        """All four seeded expenses should appear in the response body."""
        c, _ = client
        _login(c)
        response = c.get("/profile")
        body = response.data.decode()
        # Each unique description is in the page
        assert "Groceries this month" in body
        assert "Metro this month" in body
        assert "Old electricity bill" in body
        assert "Ancient shopping" in body

    def test_no_filter_all_time_button_has_active_class(self, client):
        c, _ = client
        _login(c)
        response = c.get("/profile")
        body = response.data.decode()
        # The template marks the active preset with the CSS class filter-preset-btn--active
        # The "All Time" link should carry that class when no filter is active.
        assert "filter-preset-btn--active" in body
        # Confirm it is associated with "All Time" text in the vicinity
        active_idx = body.index("filter-preset-btn--active")
        nearby = body[active_idx : active_idx + 80]
        assert "All Time" in nearby

    def test_no_filter_total_includes_all_seeded_amounts(self, client):
        """Total spent must be the sum of all four seeded expenses: 2450.00."""
        c, _ = client
        _login(c)
        response = c.get("/profile")
        body = response.data.decode()
        # Sum: 500 + 200 + 1000 + 750 = 2450
        assert "2,450.00" in body

    def test_no_filter_transaction_count_is_four(self, client):
        import re
        c, _ = client
        _login(c)
        response = c.get("/profile")
        body = response.data.decode()
        # stats.count rendered as plain integer inside the stat-value span
        counts = re.findall(r'class="stat-value">\s*(\d+)\s*<', body)
        assert "4" in counts


# ---------------------------------------------------------------------------
# 3. "This Month" preset
# ---------------------------------------------------------------------------

class TestThisMonthPreset:
    def test_this_month_returns_200(self, client):
        c, _ = client
        _login(c)
        response = c.get(f"/profile?date_from={THIS_MONTH_FROM}&date_to={THIS_MONTH_TO}")
        assert response.status_code == 200

    def test_this_month_shows_only_current_month_expenses(self, client):
        c, _ = client
        _login(c)
        response = c.get(f"/profile?date_from={THIS_MONTH_FROM}&date_to={THIS_MONTH_TO}")
        body = response.data.decode()
        assert "Groceries this month" in body
        assert "Metro this month" in body
        # Expenses from other months must not appear
        assert "Old electricity bill" not in body
        assert "Ancient shopping" not in body

    def test_this_month_stats_reflect_filtered_total(self, client):
        """Total for this month: 500 + 200 = 700."""
        c, _ = client
        _login(c)
        response = c.get(f"/profile?date_from={THIS_MONTH_FROM}&date_to={THIS_MONTH_TO}")
        body = response.data.decode()
        assert "700.00" in body

    def test_this_month_transaction_count_is_two(self, client):
        import re
        c, _ = client
        _login(c)
        response = c.get(f"/profile?date_from={THIS_MONTH_FROM}&date_to={THIS_MONTH_TO}")
        body = response.data.decode()
        counts = re.findall(r'class="stat-value">\s*(\d+)\s*<', body)
        assert "2" in counts

    def test_this_month_preset_button_is_active(self, client):
        c, _ = client
        _login(c)
        response = c.get(f"/profile?date_from={THIS_MONTH_FROM}&date_to={THIS_MONTH_TO}")
        body = response.data.decode()
        active_idx = body.index("filter-preset-btn--active")
        nearby = body[active_idx : active_idx + 80]
        assert "This Month" in nearby


# ---------------------------------------------------------------------------
# 4. "Last 3 Months" preset
# ---------------------------------------------------------------------------

class TestLast3MonthsPreset:
    def test_last_3_months_returns_200(self, client):
        c, _ = client
        _login(c)
        response = c.get(f"/profile?date_from={LAST_3_FROM}&date_to={TODAY_STR}")
        assert response.status_code == 200

    def test_last_3_months_includes_current_month_expenses(self, client):
        """Current-month expenses (within last 3 months) must appear."""
        c, _ = client
        _login(c)
        response = c.get(f"/profile?date_from={LAST_3_FROM}&date_to={TODAY_STR}")
        body = response.data.decode()
        assert "Groceries this month" in body
        assert "Metro this month" in body

    def test_last_3_months_excludes_ancient_expenses(self, client):
        """8-months-ago expense must not appear in last-3-months filter."""
        c, _ = client
        _login(c)
        response = c.get(f"/profile?date_from={LAST_3_FROM}&date_to={TODAY_STR}")
        body = response.data.decode()
        assert "Ancient shopping" not in body

    def test_last_3_months_preset_button_is_active(self, client):
        c, _ = client
        _login(c)
        response = c.get(f"/profile?date_from={LAST_3_FROM}&date_to={TODAY_STR}")
        body = response.data.decode()
        active_idx = body.index("filter-preset-btn--active")
        nearby = body[active_idx : active_idx + 100]
        assert "Last 3 Months" in nearby


# ---------------------------------------------------------------------------
# 5. "Last 6 Months" preset
# ---------------------------------------------------------------------------

class TestLast6MonthsPreset:
    def test_last_6_months_returns_200(self, client):
        c, _ = client
        _login(c)
        response = c.get(f"/profile?date_from={LAST_6_FROM}&date_to={TODAY_STR}")
        assert response.status_code == 200

    def test_last_6_months_includes_4_month_old_expense(self, client):
        """4-months-ago expense must appear in last-6-months window."""
        c, _ = client
        _login(c)
        response = c.get(f"/profile?date_from={LAST_6_FROM}&date_to={TODAY_STR}")
        body = response.data.decode()
        assert "Old electricity bill" in body

    def test_last_6_months_excludes_8_month_old_expense(self, client):
        """8-months-ago expense falls outside the 6-month window."""
        c, _ = client
        _login(c)
        response = c.get(f"/profile?date_from={LAST_6_FROM}&date_to={TODAY_STR}")
        body = response.data.decode()
        assert "Ancient shopping" not in body

    def test_last_6_months_preset_button_is_active(self, client):
        c, _ = client
        _login(c)
        response = c.get(f"/profile?date_from={LAST_6_FROM}&date_to={TODAY_STR}")
        body = response.data.decode()
        active_idx = body.index("filter-preset-btn--active")
        nearby = body[active_idx : active_idx + 100]
        assert "Last 6 Months" in nearby


# ---------------------------------------------------------------------------
# 6. "All Time" — clean URL (no params) is identical to unfiltered view
# ---------------------------------------------------------------------------

class TestAllTimeCleanUrl:
    def test_all_time_clean_url_returns_200(self, client):
        c, _ = client
        _login(c)
        response = c.get("/profile")
        assert response.status_code == 200

    def test_all_time_clean_url_shows_every_expense(self, client):
        c, _ = client
        _login(c)
        response = c.get("/profile")
        body = response.data.decode()
        assert "Groceries this month" in body
        assert "Old electricity bill" in body
        assert "Ancient shopping" in body

    def test_all_time_total_matches_sum_of_all_expenses(self, client):
        """500 + 200 + 1000 + 750 = 2450."""
        c, _ = client
        _login(c)
        response = c.get("/profile")
        body = response.data.decode()
        assert "2,450.00" in body


# ---------------------------------------------------------------------------
# 7. Custom valid date range
# ---------------------------------------------------------------------------

class TestCustomDateRange:
    def test_custom_range_returns_200(self, client):
        c, _ = client
        _login(c)
        # Range that covers only the 4-months-ago expense
        range_from = EXPENSE_DATE_OLD
        range_to = EXPENSE_DATE_OLD
        response = c.get(f"/profile?date_from={range_from}&date_to={range_to}")
        assert response.status_code == 200

    def test_custom_range_includes_only_in_range_expenses(self, client):
        c, _ = client
        _login(c)
        range_from = EXPENSE_DATE_OLD
        range_to = EXPENSE_DATE_OLD
        response = c.get(f"/profile?date_from={range_from}&date_to={range_to}")
        body = response.data.decode()
        assert "Old electricity bill" in body
        assert "Groceries this month" not in body
        assert "Ancient shopping" not in body

    def test_custom_range_stats_reflect_only_in_range_total(self, client):
        """Only 1000.00 falls within the single-day range."""
        c, _ = client
        _login(c)
        range_from = EXPENSE_DATE_OLD
        range_to = EXPENSE_DATE_OLD
        response = c.get(f"/profile?date_from={range_from}&date_to={range_to}")
        body = response.data.decode()
        assert "1,000.00" in body

    def test_custom_range_spanning_multiple_months(self, client):
        """A range covering old + current month expenses aggregates both correctly."""
        c, _ = client
        _login(c)
        # From 4-months-ago date through today captures old bill + current month items
        response = c.get(f"/profile?date_from={EXPENSE_DATE_OLD}&date_to={TODAY_STR}")
        body = response.data.decode()
        assert "Old electricity bill" in body
        assert "Groceries this month" in body
        assert "Ancient shopping" not in body

    def test_custom_range_category_breakdown_scoped_correctly(self, client):
        """Category breakdown must only include categories present in the filtered range."""
        c, _ = client
        _login(c)
        range_from = EXPENSE_DATE_CURRENT_MONTH
        range_to = EXPENSE_DATE_CURRENT_MONTH
        response = c.get(f"/profile?date_from={range_from}&date_to={range_to}")
        body = response.data.decode()
        # Food (500) and Transport (200) are in current month; Bills/Shopping are not
        assert "Food" in body
        assert "Transport" in body
        assert "Bills" not in body
        assert "Shopping" not in body


# ---------------------------------------------------------------------------
# 8. Invalid order: date_from > date_to
# ---------------------------------------------------------------------------

class TestInvalidDateOrder:
    def test_date_from_after_date_to_returns_200(self, client):
        c, _ = client
        _login(c)
        response = c.get(
            "/profile?date_from=2026-12-31&date_to=2026-01-01",
            follow_redirects=True,
        )
        assert response.status_code == 200

    def test_date_from_after_date_to_flashes_error_message(self, client):
        c, _ = client
        _login(c)
        response = c.get(
            "/profile?date_from=2026-12-31&date_to=2026-01-01",
            follow_redirects=True,
        )
        body = response.data.decode()
        assert "Start date must be before end date." in body

    def test_date_from_after_date_to_falls_back_to_unfiltered_view(self, client):
        """After the validation error the page must still show all expenses."""
        c, _ = client
        _login(c)
        response = c.get(
            "/profile?date_from=2026-12-31&date_to=2026-01-01",
            follow_redirects=True,
        )
        body = response.data.decode()
        assert "Groceries this month" in body
        assert "Old electricity bill" in body
        assert "Ancient shopping" in body

    def test_date_from_equal_to_date_to_is_valid(self, client):
        """A same-day range (from == to) is a valid filter, not an error."""
        c, _ = client
        _login(c)
        response = c.get(
            f"/profile?date_from={EXPENSE_DATE_OLD}&date_to={EXPENSE_DATE_OLD}",
            follow_redirects=True,
        )
        body = response.data.decode()
        assert "Start date must be before end date." not in body
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# 9. Malformed date strings
# ---------------------------------------------------------------------------

class TestMalformedDates:
    def test_malformed_date_from_does_not_crash(self, client):
        c, _ = client
        _login(c)
        response = c.get("/profile?date_from=not-a-date", follow_redirects=True)
        assert response.status_code == 200

    def test_malformed_date_to_does_not_crash(self, client):
        c, _ = client
        _login(c)
        response = c.get("/profile?date_to=99999-99-99", follow_redirects=True)
        assert response.status_code == 200

    def test_both_malformed_does_not_crash(self, client):
        c, _ = client
        _login(c)
        response = c.get(
            "/profile?date_from=abc&date_to=xyz", follow_redirects=True
        )
        assert response.status_code == 200

    def test_malformed_date_falls_back_to_unfiltered_view(self, client):
        """Malformed params are silently dropped; all expenses must be visible."""
        c, _ = client
        _login(c)
        response = c.get("/profile?date_from=not-a-date", follow_redirects=True)
        body = response.data.decode()
        assert "Groceries this month" in body
        assert "Old electricity bill" in body
        assert "Ancient shopping" in body

    def test_partial_valid_date_falls_back_to_unfiltered(self, client):
        """If only one of the two params is valid the filter must not activate."""
        c, _ = client
        _login(c)
        response = c.get(
            f"/profile?date_from={THIS_MONTH_FROM}&date_to=bad-date",
            follow_redirects=True,
        )
        body = response.data.decode()
        # Unfiltered: all expenses present
        assert "Ancient shopping" in body

    @pytest.mark.parametrize("bad_date", [
        "not-a-date",
        "2026/04/01",
        "01-04-2026",
        "20260401",
        "",
        "null",
        "'; DROP TABLE expenses; --",
    ])
    def test_various_malformed_date_from_values_do_not_crash(self, client, bad_date):
        c, _ = client
        _login(c)
        response = c.get(
            f"/profile?date_from={bad_date}&date_to={TODAY_STR}",
            follow_redirects=True,
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# 10. Empty period — no expenses in range
# ---------------------------------------------------------------------------

class TestEmptyPeriod:
    def test_empty_period_returns_200(self, client):
        c, _ = client
        _login(c)
        # Pick a date range guaranteed to contain no expenses
        response = c.get(
            "/profile?date_from=2000-01-01&date_to=2000-01-31",
            follow_redirects=True,
        )
        assert response.status_code == 200

    def test_empty_period_shows_no_expenses_message(self, client):
        c, _ = client
        _login(c)
        response = c.get(
            "/profile?date_from=2000-01-01&date_to=2000-01-31",
            follow_redirects=True,
        )
        body = response.data.decode()
        assert "No expenses found for this period." in body

    def test_empty_period_total_spent_is_zero(self, client):
        c, _ = client
        _login(c)
        response = c.get(
            "/profile?date_from=2000-01-01&date_to=2000-01-31",
            follow_redirects=True,
        )
        body = response.data.decode()
        assert "0.00" in body

    def test_empty_period_transaction_count_is_zero(self, client):
        import re
        c, _ = client
        _login(c)
        response = c.get(
            "/profile?date_from=2000-01-01&date_to=2000-01-31",
            follow_redirects=True,
        )
        body = response.data.decode()
        # stat-value span for Transactions must contain 0
        counts = re.findall(r'class="stat-value">\s*(\d+)\s*<', body)
        assert "0" in counts

    def test_empty_period_top_category_is_dash(self, client):
        """When there are no expenses the top category must display as '—'."""
        c, _ = client
        _login(c)
        response = c.get(
            "/profile?date_from=2000-01-01&date_to=2000-01-31",
            follow_redirects=True,
        )
        body = response.data.decode()
        assert "—" in body


# ---------------------------------------------------------------------------
# 11. ₹ symbol always present
# ---------------------------------------------------------------------------

class TestRupeeSymbol:
    def test_rupee_symbol_present_with_no_filter(self, client):
        c, _ = client
        _login(c)
        body = c.get("/profile").data.decode()
        assert "₹" in body

    def test_rupee_symbol_present_with_this_month_filter(self, client):
        c, _ = client
        _login(c)
        body = c.get(
            f"/profile?date_from={THIS_MONTH_FROM}&date_to={THIS_MONTH_TO}"
        ).data.decode()
        assert "₹" in body

    def test_rupee_symbol_present_with_custom_filter(self, client):
        c, _ = client
        _login(c)
        body = c.get(
            f"/profile?date_from={EXPENSE_DATE_OLD}&date_to={EXPENSE_DATE_OLD}"
        ).data.decode()
        assert "₹" in body

    def test_rupee_symbol_present_on_empty_period(self, client):
        """Even when no expenses are in range, stats still render ₹0.00."""
        c, _ = client
        _login(c)
        body = c.get(
            "/profile?date_from=2000-01-01&date_to=2000-01-31"
        ).data.decode()
        assert "₹" in body

    def test_amounts_never_display_dollar_sign(self, client):
        c, _ = client
        _login(c)
        body = c.get("/profile").data.decode()
        assert "$" not in body


# ---------------------------------------------------------------------------
# 12. Query helper unit tests — signatures and filtering behaviour
# ---------------------------------------------------------------------------

class TestQueryHelpers:
    """
    These tests call the query functions directly against the temp DB,
    verifying that the signatures accept date_from/date_to kwargs and that
    filtering works correctly in isolation from the HTTP layer.
    """

    def _user_id(self):
        conn = get_db()
        row = conn.execute(
            "SELECT id FROM users WHERE email = ?", ("test@spendly.com",)
        ).fetchone()
        conn.close()
        return row["id"]

    # --- get_summary_stats ---

    def test_get_summary_stats_accepts_date_kwargs(self, client):
        """get_summary_stats must accept date_from and date_to keyword args."""
        _, user_id = client
        with app.app_context():
            result = get_summary_stats(user_id, date_from=None, date_to=None)
        assert isinstance(result, dict)
        assert "total" in result
        assert "count" in result
        assert "top_category" in result

    def test_get_summary_stats_no_filter_returns_all(self, client):
        _, user_id = client
        with app.app_context():
            result = get_summary_stats(user_id)
        # 500 + 200 + 1000 + 750 = 2450
        assert result["total"] == "2,450.00"
        assert result["count"] == 4

    def test_get_summary_stats_filtered_returns_subset(self, client):
        _, user_id = client
        with app.app_context():
            result = get_summary_stats(
                user_id,
                date_from=EXPENSE_DATE_CURRENT_MONTH,
                date_to=EXPENSE_DATE_CURRENT_MONTH,
            )
        # 500 + 200 = 700
        assert result["total"] == "700.00"
        assert result["count"] == 2

    def test_get_summary_stats_empty_range_returns_zero(self, client):
        _, user_id = client
        with app.app_context():
            result = get_summary_stats(
                user_id, date_from="2000-01-01", date_to="2000-01-31"
            )
        assert result["total"] == "0.00"
        assert result["count"] == 0
        assert result["top_category"] == "—"

    def test_get_summary_stats_top_category_reflects_filter(self, client):
        """Within the current-month filter the top category by spend is Food (500)."""
        _, user_id = client
        with app.app_context():
            result = get_summary_stats(
                user_id,
                date_from=EXPENSE_DATE_CURRENT_MONTH,
                date_to=EXPENSE_DATE_CURRENT_MONTH,
            )
        assert result["top_category"] == "Food"

    # --- get_recent_transactions ---

    def test_get_recent_transactions_accepts_date_kwargs(self, client):
        _, user_id = client
        with app.app_context():
            result = get_recent_transactions(user_id, date_from=None, date_to=None)
        assert isinstance(result, list)

    def test_get_recent_transactions_no_filter_returns_all(self, client):
        _, user_id = client
        with app.app_context():
            result = get_recent_transactions(user_id)
        assert len(result) == 4

    def test_get_recent_transactions_filtered_returns_subset(self, client):
        _, user_id = client
        with app.app_context():
            result = get_recent_transactions(
                user_id,
                date_from=EXPENSE_DATE_CURRENT_MONTH,
                date_to=EXPENSE_DATE_CURRENT_MONTH,
            )
        assert len(result) == 2
        descriptions = [tx["description"] for tx in result]
        assert "Groceries this month" in descriptions
        assert "Metro this month" in descriptions

    def test_get_recent_transactions_returns_dicts_with_required_keys(self, client):
        _, user_id = client
        with app.app_context():
            result = get_recent_transactions(user_id)
        assert len(result) > 0
        for tx in result:
            assert "date" in tx
            assert "description" in tx
            assert "category" in tx
            assert "amount" in tx

    def test_get_recent_transactions_amount_is_formatted_string(self, client):
        """Amounts must be formatted strings like '500.00', not raw floats."""
        _, user_id = client
        with app.app_context():
            result = get_recent_transactions(
                user_id,
                date_from=EXPENSE_DATE_CURRENT_MONTH,
                date_to=EXPENSE_DATE_CURRENT_MONTH,
            )
        for tx in result:
            assert isinstance(tx["amount"], str)
            # Must be parseable as a number
            float(tx["amount"].replace(",", ""))

    def test_get_recent_transactions_ordered_by_date_desc(self, client):
        """Most recent expense must appear first."""
        _, user_id = client
        with app.app_context():
            result = get_recent_transactions(user_id)
        dates = [tx["date"] for tx in result]
        # Dates come back in display format e.g. "01 Jan 2026"; check order via index
        from datetime import datetime as _dt
        parsed = [_dt.strptime(d, "%d %b %Y") for d in dates]
        assert parsed == sorted(parsed, reverse=True)

    def test_get_recent_transactions_empty_range_returns_empty_list(self, client):
        _, user_id = client
        with app.app_context():
            result = get_recent_transactions(
                user_id, date_from="2000-01-01", date_to="2000-01-31"
            )
        assert result == []

    # --- get_category_breakdown ---

    def test_get_category_breakdown_accepts_date_kwargs(self, client):
        _, user_id = client
        with app.app_context():
            result = get_category_breakdown(user_id, date_from=None, date_to=None)
        assert isinstance(result, list)

    def test_get_category_breakdown_no_filter_includes_all_categories(self, client):
        _, user_id = client
        with app.app_context():
            result = get_category_breakdown(user_id)
        names = {cat["name"] for cat in result}
        assert "Food" in names
        assert "Transport" in names
        assert "Bills" in names
        assert "Shopping" in names

    def test_get_category_breakdown_filtered_excludes_out_of_range_categories(self, client):
        _, user_id = client
        with app.app_context():
            result = get_category_breakdown(
                user_id,
                date_from=EXPENSE_DATE_CURRENT_MONTH,
                date_to=EXPENSE_DATE_CURRENT_MONTH,
            )
        names = {cat["name"] for cat in result}
        assert "Food" in names
        assert "Transport" in names
        assert "Bills" not in names
        assert "Shopping" not in names

    def test_get_category_breakdown_returns_dicts_with_required_keys(self, client):
        _, user_id = client
        with app.app_context():
            result = get_category_breakdown(user_id)
        for cat in result:
            assert "name" in cat
            assert "amount" in cat
            assert "percent" in cat

    def test_get_category_breakdown_percentages_sum_to_100(self, client):
        _, user_id = client
        with app.app_context():
            result = get_category_breakdown(user_id)
        if result:
            total_pct = sum(cat["percent"] for cat in result)
            assert total_pct == 100

    def test_get_category_breakdown_empty_range_returns_empty_list(self, client):
        _, user_id = client
        with app.app_context():
            result = get_category_breakdown(
                user_id, date_from="2000-01-01", date_to="2000-01-31"
            )
        assert result == []

    def test_get_category_breakdown_amount_is_formatted_string(self, client):
        _, user_id = client
        with app.app_context():
            result = get_category_breakdown(user_id)
        for cat in result:
            assert isinstance(cat["amount"], str)
            float(cat["amount"].replace(",", ""))

    # --- SQL injection safety ---
    #
    # The helpers in database/queries.py bind date_from/date_to as parameters, so
    # a SQL payload arrives as a literal string value and never as executable SQL.
    #
    # Note on what NOT to assert: "'; DROP TABLE expenses; --" sorts BELOW every
    # real ISO date ("'" is ASCII 39, "2" is 50), so
    # `date BETWEEN <payload> AND <today>` legitimately matches every row. A
    # non-empty result is therefore correct behaviour, not evidence of a leak.
    # The contract under test is the one these tests are named for: the call
    # returns normally and the schema survives.

    INJECTION = "'; DROP TABLE expenses; --"

    @staticmethod
    def _expenses_table_exists():
        conn = get_db()
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'expenses'"
        ).fetchone()
        conn.close()
        return row is not None

    def test_get_summary_stats_sql_injection_in_date_param_does_not_crash(self, client):
        _, user_id = client
        with app.app_context():
            result = get_summary_stats(
                user_id, date_from=self.INJECTION, date_to=TODAY_STR
            )
        assert isinstance(result["count"], int), "helper must return normally"
        assert self._expenses_table_exists(), "payload must not have dropped the table"

    def test_get_recent_transactions_sql_injection_does_not_crash(self, client):
        _, user_id = client
        with app.app_context():
            result = get_recent_transactions(
                user_id, date_from=self.INJECTION, date_to=TODAY_STR
            )
        assert isinstance(result, list), "helper must return normally"
        assert self._expenses_table_exists(), "payload must not have dropped the table"

    def test_get_category_breakdown_sql_injection_does_not_crash(self, client):
        _, user_id = client
        with app.app_context():
            result = get_category_breakdown(
                user_id, date_from=self.INJECTION, date_to=TODAY_STR
            )
        assert isinstance(result, list), "helper must return normally"
        assert self._expenses_table_exists(), "payload must not have dropped the table"
