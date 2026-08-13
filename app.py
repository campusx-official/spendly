import calendar
import csv
import io
import os
import sqlite3
from datetime import date, datetime

from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash

from database.db import (
    create_user,
    db_is_healthy,
    get_db,
    get_user_by_email,
    init_db,
    seed_db,
)
from database.queries import (
    delete_expense_by_id,
    get_category_breakdown,
    get_expense_by_id,
    get_expenses_for_export,
    get_recent_transactions,
    get_summary_stats,
    get_user_by_id,
    insert_expense,
    update_expense,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SPENDLY_SECRET_KEY", "dev-secret-key")

if os.environ.get("SPENDLY_ENV") == "production" and app.secret_key == "dev-secret-key":
    raise RuntimeError("SPENDLY_SECRET_KEY must be set when SPENDLY_ENV=production")

CATEGORIES = [
    "Food",
    "Transport",
    "Bills",
    "Health",
    "Entertainment",
    "Shopping",
    "Other",
]

with app.app_context():
    init_db()
    if os.environ.get("SPENDLY_SEED", "1") == "1":
        seed_db()


def _parse_date(val):
    try:
        datetime.strptime(val, "%Y-%m-%d")
        return val
    except (ValueError, TypeError):
        return None


def _csv_safe(value):
    """Neutralise a cell a spreadsheet would evaluate as a formula.

    Excel and Sheets treat a leading =, +, - or @ as the start of a formula,
    so free text like "=cmd|'/c calc'!A1" would execute on open (CWE-1236).
    Prefixing an apostrophe forces the cell to be read as text.

    The trigger is tested against the leading-whitespace-stripped value,
    because a spreadsheet trims before it evaluates — " =1+1" is as dangerous
    as "=1+1".

    Applied to every free-text column, not only the ones lacking input
    validation. `/expenses/add` and `/expenses/<id>/edit` do constrain
    category to CATEGORIES, but `database/db.py` declares it as plain
    `TEXT NOT NULL` with no CHECK constraint, so seeds and any future writer
    are not bound by that check. For a valid category this is a no-op.

    This is a presentation concern, so it lives here rather than in the query
    layer — get_expenses_for_export() deliberately returns raw values.
    """
    if value is None:
        return ""
    text = str(value)
    if text.lstrip()[:1] in ("=", "+", "-", "@"):
        return "'" + text
    return text


def _months_ago(today, n):
    m, y = today.month - n, today.year
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1).isoformat()


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #


@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("profile"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not all([name, email, password, confirm_password]):
            flash("All fields are required.", "error")
            return render_template("register.html")

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("register.html")

        try:
            create_user(name, email, password)
        except sqlite3.IntegrityError:
            flash("Email already registered.", "error")
            return render_template("register.html")

        flash("Account created! Please sign in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("profile"))
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        user = get_user_by_email(email)
        if not user or not check_password_hash(user["password_hash"], password):
            flash("Invalid email or password.", "error")
            return render_template("login.html")

        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        return redirect(url_for("profile"))

    return render_template("login.html")


@app.route("/healthz")
def healthz():
    """Liveness — process is up. Deliberately does not touch the DB, so a
    locked/slow database never turns into a restart loop."""
    return {"status": "ok"}, 200


@app.route("/readyz")
def readyz():
    """Readiness — the DB is reachable and writable."""
    if not db_is_healthy():
        abort(503)
    return {"status": "ready"}, 200


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("landing"))


@app.route("/profile")
def profile():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    uid = session["user_id"]
    today = date.today()

    date_from = _parse_date(request.args.get("date_from"))
    date_to = _parse_date(request.args.get("date_to"))

    if date_from and date_to and date_from > date_to:
        flash("Start date must be before end date.", "error")
        date_from = date_to = None

    today_str = today.isoformat()
    this_month_from = today.replace(day=1).isoformat()
    this_month_to = today.replace(
        day=calendar.monthrange(today.year, today.month)[1]
    ).isoformat()

    presets = {
        "this_month": {"date_from": this_month_from, "date_to": this_month_to},
        "last_3": {"date_from": _months_ago(today, 3), "date_to": today_str},
        "last_6": {"date_from": _months_ago(today, 6), "date_to": today_str},
    }

    return render_template(
        "profile.html",
        user=get_user_by_id(uid),
        stats=get_summary_stats(uid, date_from, date_to),
        expenses=get_recent_transactions(uid, date_from=date_from, date_to=date_to),
        categories=get_category_breakdown(uid, date_from, date_to),
        date_from=date_from,
        date_to=date_to,
        presets=presets,
    )


@app.route("/analytics")
def analytics():
    if not session.get("user_id"):
        return redirect(url_for("login"))
    return render_template("analytics.html")


@app.route("/expenses/add", methods=["GET", "POST"])
def add_expense():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    today = date.today().isoformat()

    if request.method == "POST":
        amount_raw = request.form.get("amount", "").strip()
        category = request.form.get("category", "").strip()
        expense_date = request.form.get("date", "").strip()
        description = request.form.get("description", "").strip()

        try:
            amount = float(amount_raw)
            if amount <= 0:
                raise ValueError
        except ValueError:
            flash("Amount must be a positive number.", "error")
            return render_template(
                "add_expense.html",
                categories=CATEGORIES,
                form=request.form,
                today=today,
            )

        if category not in CATEGORIES:
            flash("Please select a valid category.", "error")
            return render_template(
                "add_expense.html",
                categories=CATEGORIES,
                form=request.form,
                today=today,
            )

        if not _parse_date(expense_date):
            flash("Please enter a valid date.", "error")
            return render_template(
                "add_expense.html",
                categories=CATEGORIES,
                form=request.form,
                today=today,
            )

        insert_expense(session["user_id"], amount, category, expense_date, description)
        flash("Expense added.", "success")
        return redirect(url_for("profile"))

    return render_template(
        "add_expense.html", categories=CATEGORIES, form={}, today=today
    )


@app.route("/expenses/<int:id>/edit", methods=["GET", "POST"])
def edit_expense(id):
    if not session.get("user_id"):
        return redirect(url_for("login"))

    expense = get_expense_by_id(id, session["user_id"])
    if expense is None:
        abort(404)

    if request.method == "GET":
        return render_template(
            "edit_expense.html",
            expense=expense,
            categories=CATEGORIES,
            form={},
        )

    amount_raw = request.form.get("amount", "").strip()
    category = request.form.get("category", "").strip()
    expense_date = request.form.get("date", "").strip()
    description = request.form.get("description", "").strip()

    try:
        amount = float(amount_raw)
        if amount <= 0:
            raise ValueError
    except ValueError:
        flash("Amount must be a positive number.", "error")
        return render_template(
            "edit_expense.html",
            expense=expense,
            categories=CATEGORIES,
            form=request.form,
        )

    if category not in CATEGORIES:
        flash("Please select a valid category.", "error")
        return render_template(
            "edit_expense.html",
            expense=expense,
            categories=CATEGORIES,
            form=request.form,
        )

    if not _parse_date(expense_date):
        flash("Please enter a valid date.", "error")
        return render_template(
            "edit_expense.html",
            expense=expense,
            categories=CATEGORIES,
            form=request.form,
        )

    update_expense(id, session["user_id"], amount, category, expense_date, description)
    flash("Expense updated.", "success")
    return redirect(url_for("profile"))


@app.route("/expenses/<int:id>/delete", methods=["POST"])
def delete_expense(id):
    if not session.get("user_id"):
        return redirect(url_for("login"))

    expense = get_expense_by_id(id, session["user_id"])
    if expense is None:
        abort(404)

    delete_expense_by_id(id, session["user_id"])
    return redirect(url_for("profile"))


# The only route that returns a file rather than a template — a deliberate
# exception, not a new default.
@app.route("/expenses/export")
def export_expenses():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    date_from = _parse_date(request.args.get("date_from"))
    date_to = _parse_date(request.args.get("date_to"))

    # Mirror the profile's handling of an inverted range so the export and the
    # table it sits next to never disagree. No flash() here: a file download
    # renders no page, so the message would surface later on an unrelated one.
    if date_from and date_to and date_from > date_to:
        date_from = date_to = None

    rows = get_expenses_for_export(session["user_id"], date_from, date_to)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["date", "category", "amount", "description"])
    for row in rows:
        writer.writerow(
            [
                row["date"],
                _csv_safe(row["category"]),
                row["amount"],
                _csv_safe(row["description"]),
            ]
        )

    if date_from and date_to:
        stamp = f"{date_from}_to_{date_to}"
    else:
        stamp = date.today().isoformat()

    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="spendly-expenses-{stamp}.csv"'
            )
        },
    )


if __name__ == "__main__":
    app.run(debug=True, port=5001)
