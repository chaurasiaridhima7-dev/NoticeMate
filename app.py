
from flask import Flask, render_template, request, redirect, jsonify , session
import sqlite3
import re
from datetime import date, timedelta, datetime
from werkzeug.security import generate_password_hash, check_password_hash
import os
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
app.secret_key = os.environ.get(
    "SECRET_KEY",
    "noticemate-local-development-key"
)

class PostgreSQLConnection:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, query, parameters=()):
        query = query.replace("?", "%s")
        cursor = self.connection.cursor()
        cursor.execute(query, parameters)
        return cursor

    def commit(self):
        self.connection.commit()

    def close(self):
        self.connection.close()

def get_db():
    database_url = os.environ.get("DATABASE_URL")

    if database_url:
        conn = psycopg2.connect(
            database_url,
            cursor_factory=RealDictCursor
        )
        return PostgreSQLConnection(conn)

    conn = sqlite3.connect("notices.db")
    conn.row_factory = sqlite3.Row
    return conn



def create_table():
    conn = get_db()

    if isinstance(conn, PostgreSQLConnection):

        conn.execute("""
            CREATE TABLE IF NOT EXISTS students (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS notices (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                category TEXT NOT NULL,
                deadline TEXT,
                student_id INTEGER
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id SERIAL PRIMARY KEY,
                notice_id INTEGER NOT NULL,
                reminder_date TEXT NOT NULL,
                notified INTEGER DEFAULT 0,
                FOREIGN KEY (notice_id) REFERENCES notices(id)
            )
        """)

    else:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS notices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                category TEXT NOT NULL,
                deadline TEXT,
                student_id INTEGER
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                notice_id INTEGER NOT NULL,
                reminder_date TEXT NOT NULL,
                notified INTEGER DEFAULT 0,
                FOREIGN KEY (notice_id) REFERENCES notices(id)
            )
        """)

        columns = [
            column["name"]
            for column in conn.execute(
                "PRAGMA table_info(notices)"
            ).fetchall()
        ]

        if "student_id" not in columns:
            conn.execute(
                "ALTER TABLE notices ADD COLUMN student_id INTEGER"
            )

    conn.execute("""
        UPDATE notices
        SET student_id = (
            SELECT id FROM students ORDER BY id LIMIT 1
        )
        WHERE student_id IS NULL
    """)

    conn.commit()
    conn.close()

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        hashed_password = generate_password_hash(password)

        conn = get_db()

               
        try:
            conn.execute(
                "INSERT INTO students (name, email, password) VALUES (?, ?, ?)",
                (name, email, hashed_password)
            )

            conn.commit()
            conn.close()

            return redirect("/login")


        except (sqlite3.IntegrityError, psycopg2.IntegrityError):
            conn.close()
            return "This email is already registered."

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        conn = get_db()

        student = conn.execute(
           "SELECT * FROM students WHERE LOWER(TRIM(email)) = ?",
            (email,)
        ).fetchone()

        conn.close()

        if student and check_password_hash(
            student["password"], password
        ):
            session["student_id"] = student["id"]
            session["student_name"] = student["name"]

            return redirect("/")

        return "Invalid email or password."

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/")
def home():
    if "student_id" not in session:
        return redirect("/login")

    conn = get_db()

    notices = conn.execute(
        "SELECT * FROM notices WHERE student_id = ? ORDER BY id DESC",
        (session["student_id"],)
    ).fetchall()

    reminders = conn.execute(
        "SELECT reminders.* FROM reminders "
        "JOIN notices ON reminders.notice_id = notices.id "
        "WHERE notices.student_id = ?",
        (session["student_id"],)
    ).fetchall()

    reminder_ids = [r["notice_id"] for r in reminders]

    conn.close()

    today = date.today().isoformat()

    total_notices = len(notices)

    assignment_count = sum(
        1 for notice in notices
        if notice["category"].lower() == "assignment"
    )

    upcoming_exam_count = sum(
        1 for notice in notices
        if notice["category"].lower() == "examination"
        and notice["deadline"]
        and notice["deadline"] >= today
    )

    return render_template(
        "index.html",
        notices=notices,
        today=today,
        reminder_ids=reminder_ids,
        reminders=reminders,
        student_name=session["student_name"],
        total_notices=total_notices,
        assignment_count=assignment_count,
        upcoming_exam_count=upcoming_exam_count
    )





@app.route("/add_notice", methods=["POST"])
def add_notice():
    if "student_id" not in session:
        return redirect("/login")

    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    category = request.form.get("category", "")
    deadline = request.form.get("deadline", "")

    allowed_categories = [
        "assignment", "examination",
        "event", "scholarship"
    ]

    if title and description and category in allowed_categories:
        conn = get_db()

       
        conn.execute(
                "INSERT INTO notices (title, description, category, deadline, student_id) VALUES (?, ?, ?, ?, ?)",
                (title, description, category, deadline, session["student_id"])
            )


        conn.commit()
        conn.close()

    return redirect("/")
    


def identify_category(message):
    message = message.lower()

    keywords = {
        "scholarship": [
            "scholarship", "financial aid", "stipend"
        ],
        "examination": [
            "exam", "examination", "timetable",
            "hall ticket", "results"
        ],
        "event": [
            "event", "fest", "competition",
            "workshop", "seminar"
        ],
        "assignment": [
            "assignment", "project", "coursework",
            "submission"
        ]
    }

    scores = {}

    for category, words in keywords.items():
        scores[category] = sum(
    bool(re.search(r"\b" + re.escape(word) + r"\b", message))
    for word in words
)

    best_category = max(scores, key=scores.get)

    if scores[best_category] == 0:
        return "assignment"

    return best_category

def extract_deadline(message):

    today = date.today()

    date_pattern = (
        r"\b(?:tomorrow|next\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
        r"|\d{1,2}(?:st|nd|rd|th)?\s+"
        r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
        r",?\s*\d{0,4}"
        r"|\d{1,2}[/-]\d{1,2}[/-]\d{4})\b"
    )

    def parse_date(value):

        value = value.strip()

        if value.lower() == "tomorrow":
            return (today + timedelta(days=1)).isoformat()

        weekday_match = re.fullmatch(
            r"next\s+(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)",
            value,
            re.IGNORECASE
        )

        if weekday_match:
            weekdays = {
                "monday": 0, "tuesday": 1,
                "wednesday": 2, "thursday": 3,
                "friday": 4, "saturday": 5,
                "sunday": 6
            }

            target = weekdays[weekday_match.group(1).lower()]
            days = (target - today.weekday()) % 7

            if days == 0:
                days = 7

            return (today + timedelta(days=days)).isoformat()

        try:
            if "/" in value or "-" in value:
                return datetime.strptime(
                    value.replace("-", "/"), "%d/%m/%Y"
                ).date().isoformat()

            cleaned = re.sub(
                r"(\d+)(st|nd|rd|th)",
                r"\1", value, flags=re.IGNORECASE
            )

            result = datetime.strptime(
                cleaned.strip(), "%d %B %Y"
            ).date() if re.search(r"\d{4}", cleaned) else datetime.strptime(
                cleaned.strip(), "%d %B"
            ).date().replace(year=today.year)

            if result < today and not re.search(r"\d{4}", cleaned):
                result = result.replace(year=today.year + 1)

            return result.isoformat()

        except ValueError:
            return ""

    keywords = [
        "last date",
        "deadline",
        "due date",
        "due by",
        "submit before",
        "submission date",
        "submission deadline",
        "closing date"
    ]

    for keyword in keywords:
        match = re.search(
            re.escape(keyword), message, re.IGNORECASE
        )

        if match:
            following_text = message[
                match.end():match.end() + 150
            ]

            date_match = re.search(
                date_pattern, following_text, re.IGNORECASE
            )

            if date_match:
                result = parse_date(date_match.group())

                if result:
                    return result

    date_match = re.search(
        date_pattern, message, re.IGNORECASE
    )

    if date_match:
        return parse_date(date_match.group())

    return ""

@app.route("/import_notice", methods=["POST"])
def import_notice():
    if "student_id" not in session:
        return redirect("/login")

    message = request.form.get("message", "").strip()

    if message:
        category = identify_category(message)
        title = message.split("\n")[0][:80]
        deadline = extract_deadline(message)

        conn = get_db()

        conn.execute(
            "INSERT INTO notices (title, description, category, deadline, student_id) VALUES (?, ?, ?, ?, ?)",
            (title, message, category, deadline, session["student_id"])
        )

        conn.commit()
        conn.close()

    return redirect("/")  




@app.route("/delete_notice/<int:notice_id>", methods=["POST"])
def delete_notice(notice_id):
    if "student_id" not in session:
        return redirect("/login")

    conn = get_db()

    conn.execute(
        "DELETE FROM reminders WHERE notice_id = ?",
        (notice_id,)
    )

    conn.execute(
        "DELETE FROM notices WHERE id = ? AND student_id = ?",
        (notice_id, session["student_id"])
    )

    conn.commit()
    conn.close()

    return redirect("/")



@app.route("/edit_notice/<int:notice_id>", methods=["GET", "POST"])
def edit_notice(notice_id):
    if "student_id" not in session:
        return redirect("/login")

    conn = get_db()

    notice = conn.execute(
        "SELECT * FROM notices WHERE id = ? AND student_id = ?",
        (notice_id, session["student_id"])
    ).fetchone()

    if notice is None:
        conn.close()
        return redirect("/")

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        category = request.form.get("category", "")
        deadline = request.form.get("deadline", "")

        allowed_categories = [
            "assignment", "examination",
            "event", "scholarship"
        ]

        if title and description and category in allowed_categories:              
                       conn.execute(
                "UPDATE notices SET title = ?, description = ?, category = ?, deadline = ? WHERE id = ? AND student_id = ?",
                (title, description, category, deadline, notice_id, session["student_id"])
            )
    conn.commit()
    

    conn.close()
    return redirect("/")

    conn.close()

    return render_template("edit.html", notice=notice)


@app.route("/set_reminder/<int:notice_id>", methods=["POST"])
def set_reminder(notice_id):
    if "student_id" not in session:
        return redirect("/login")

    conn = get_db()

    notice = conn.execute(
        "SELECT * FROM notices WHERE id = ? AND student_id = ?",
        (notice_id, session["student_id"])
    ).fetchone()

    if notice is None or not notice["deadline"]:
        conn.close()
        return redirect("/")

    reminder_date = (
        date.fromisoformat(notice["deadline"]) - timedelta(days=1)
    ).isoformat()

    existing = conn.execute(
        "SELECT * FROM reminders WHERE notice_id = ?",
        (notice_id,)
    ).fetchone()

    if existing is None:
        conn.execute(
            "INSERT INTO reminders (notice_id, reminder_date) VALUES (?, ?)",
            (notice_id, reminder_date)
        )

    conn.commit()
    conn.close()

    return redirect("/")



@app.route("/check_reminders")
def check_reminders():
    if "student_id" not in session:
        return jsonify([])

    conn = get_db()
    today = date.today().isoformat()

    due_reminders = conn.execute(
        "SELECT reminders.id, notices.title "
        "FROM reminders "
        "JOIN notices ON reminders.notice_id = notices.id "
        "WHERE reminders.reminder_date <= ? "
        "AND reminders.notified = 0 "
        "AND notices.student_id = ?",
        (today, session["student_id"])
    ).fetchall()

    for reminder in due_reminders:
        conn.execute(
            "UPDATE reminders SET notified = 1 WHERE id = ?",
            (reminder["id"],)
        )

    conn.commit()
    conn.close()

    return jsonify([
        {"title": reminder["title"]}
        for reminder in due_reminders
    ])
create_table()

if __name__ == "__main__":
    app.run(debug=True)
    