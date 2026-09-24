"""
MyNextStepHealth - Patient Intake and Triage System
====================================================
A Flask web application for digital patient intake forms.
Stores submissions in SQLite and sends email notifications.

To run:
    1. Install requirements: pip install flask
    2. Set your email credentials below (EMAIL_ADDRESS and EMAIL_PASSWORD)
    3. Run: python app.py
    4. Open browser: http://127.0.0.1:5000
"""

from flask import Flask, render_template, request, redirect, url_for, flash
from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import sqlite3
import smtplib
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import os

# ─────────────────────────────────────────────
# App Configuration
# ─────────────────────────────────────────────
# ── Load secrets from ~/.env (never commit or upload this file) ──
# On PythonAnywhere: create /home/YOURNAME/.env containing
#     MNSH_EMAIL=mynextstep@gmail.com
#     MNSH_PASSWORD=your16charapppassword
#     MNSH_SECRET=a-long-random-string
_env_path = os.path.join(os.path.expanduser("~"), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if "=" in _line and not _line.startswith("#"):
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

app = Flask(__name__)

# Signs the session cookie. Falls back to a random value so the app
# still runs locally, but sessions reset on every restart until set.
app.secret_key = os.environ.get("MNSH_SECRET") or os.urandom(32).hex()

# ── CSRF PROTECTION ───────────────────────────
# Blocks a malicious site from making a visitor's browser POST to your
# forms without them knowing. Every POST must now carry a token that
# only your own pages hand out. Add to each form:
#     <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
csrf = CSRFProtect(app)

# Session cookie hardening
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,   # JavaScript can't read the cookie
    SESSION_COOKIE_SAMESITE="Lax",  # not sent on cross-site POSTs
    SESSION_COOKIE_SECURE=True,     # HTTPS only (your live site is HTTPS)
    WTF_CSRF_TIME_LIMIT=None,       # don't expire mid-form; patients are slow
)

# ── RATE LIMITING ─────────────────────────────
# Stops one person scripting thousands of submissions and burning
# your Gmail quota. Counts are held in memory, so they reset when the
# app restarts — fine at this scale.
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],              # no global limit; applied per route
    storage_uri="memory://",
)

# Database file location (created automatically on first run)
# Absolute path: under WSGI the working directory isn't the app folder
DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "mynextstephealth.db")

# ─────────────────────────────────────────────
# Email Configuration
# Replace these with your real Gmail credentials.
# For Gmail: enable "App Passwords" in Google Account > Security
# Then paste the 16-character app password below.
# ─────────────────────────────────────────────


# ── EMAIL CREDENTIALS (from .env — never hardcode these) ──
EMAIL_ADDRESS  = os.environ.get("MNSH_EMAIL", "")
EMAIL_PASSWORD = os.environ.get("MNSH_PASSWORD", "")


# ── CONTACT FORM ──
CONTACT_TO = "mynextstep@gmail.com"     # where website enquiries are sent
EMAIL_RE   = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ── CLINICS ──
# Clinics now live in the database (see init_db and get_clinics below),
# so adding a new customer is one SQL insert — no code change, no redeploy.
# The two clinics that used to be hardcoded here are seeded automatically
# the first time the app runs.

# ─────────────────────────────────────────────
# Database Helpers
# ─────────────────────────────────────────────
def get_db():
    """Open a connection to the SQLite database."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row   # Allows dict-style column access
    return conn


def init_db():
    """Create the patients table if it doesn't exist yet."""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS patients (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            clinic_name TEXT    NOT NULL,
            full_name   TEXT    NOT NULL,
            email       TEXT    NOT NULL,
            phone       TEXT    NOT NULL,
            concern     TEXT    NOT NULL,
            urgency     TEXT    NOT NULL,
            notes       TEXT,
            status      TEXT    NOT NULL DEFAULT 'New',
            submitted_at TEXT   NOT NULL
        )
    """)

    # ── CONTACT FORM: stores website enquiries ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS contact_messages (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT    NOT NULL,
            email        TEXT    NOT NULL,
            organisation TEXT,
            subject      TEXT    NOT NULL,
            message      TEXT    NOT NULL,
            emailed      INTEGER NOT NULL DEFAULT 0,
            submitted_at TEXT    NOT NULL
        )
    """)

    # ── CLINICS: one row per site. org_slug groups sites under a customer ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clinics (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            org_slug TEXT    NOT NULL,          -- the CUSTOMER  (e.g. "riverside")
            slug     TEXT    NOT NULL UNIQUE,   -- this SITE     (e.g. "riverside-north")
            name     TEXT    NOT NULL,          -- shown to patients
            email    TEXT    NOT NULL,          -- where their requests are sent
            active   INTEGER NOT NULL DEFAULT 1
        )
    """)

    # Seed the two original clinics the first time only
    if conn.execute("SELECT COUNT(*) FROM clinics").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO clinics (org_slug, slug, name, email) VALUES (?, ?, ?, ?)",
            [
                ("bowes-road",   "bowes-road-dental",
                 "Bowes Road Dental Practice", "lacagmaster@gmail.com"),
                ("medi-family",  "medi-family",
                 "Medi Family Clinic",         "trackablewalts@gmail.com"),
            ],
        )

    conn.commit()
    conn.close()


# ── CLINIC LOOKUPS ────────────────────────────
def get_clinics(org_slug=None, clinic_slug=None):
    """Which clinics may this patient choose from?

    clinic_slug -> just that one site      (link had ?clinic=...)
    org_slug    -> every site for that customer (link had ?org=...)
    neither     -> all active clinics
    """
    conn = get_db()
    if clinic_slug:
        rows = conn.execute(
            "SELECT * FROM clinics WHERE slug = ? AND active = 1", (clinic_slug,)
        ).fetchall()
    elif org_slug:
        rows = conn.execute(
            "SELECT * FROM clinics WHERE org_slug = ? AND active = 1 ORDER BY name",
            (org_slug,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM clinics WHERE active = 1 ORDER BY name"
        ).fetchall()
    conn.close()
    return rows


def get_clinic_email(slug):
    """Where should this clinic's requests be emailed?"""
    conn = get_db()
    row = conn.execute(
        "SELECT email FROM clinics WHERE slug = ? AND active = 1", (slug,)
    ).fetchone()
    conn.close()
    return row["email"] if row else None


# ─────────────────────────────────────────────
# Email Notification
# ─────────────────────────────────────────────
def send_email_notification(patient_data: dict, clinic_email: str):
    """
    Send an email to NOTIFY_EMAIL with the real patient submission data.
    Uses Gmail SMTP with TLS encryption.
    """
    try:
        # Build a clean HTML email body with the actual submitted values
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #1a1a2e; max-width: 600px; margin: auto;">
            <div style="background:#1B3A6B; padding:24px; border-radius:8px 8px 0 0;">
                <h2 style="color:#ffffff; margin:0;">🏥 New Patient Intake — MyNextStepHealth</h2>
            </div>
            <div style="background:#f4f8ff; padding:24px; border-radius:0 0 8px 8px; border:1px solid #d0dff0;">
                <p style="margin-top:0; color:#555;">A new patient intake form has been submitted. Details below:</p>

                <table style="width:100%; border-collapse:collapse;">
                    <tr>
                        <td style="padding:10px; background:#ffffff; border:1px solid #d0dff0; width:35%;"><strong>Clinic</strong></td>
                        <td style="padding:10px; background:#ffffff; border:1px solid #d0dff0;">{patient_data['clinic_name']}</td>
                    </tr>
                    <tr>
                        <td style="padding:10px; background:#f9fbff; border:1px solid #d0dff0;"><strong>Patient Name</strong></td>
                        <td style="padding:10px; background:#f9fbff; border:1px solid #d0dff0;">{patient_data['full_name']}</td>
                    </tr>
                    <tr>
                        <td style="padding:10px; background:#ffffff; border:1px solid #d0dff0;"><strong>Email</strong></td>
                        <td style="padding:10px; background:#ffffff; border:1px solid #d0dff0;">{patient_data['email']}</td>
                    </tr>
                    <tr>
                        <td style="padding:10px; background:#f9fbff; border:1px solid #d0dff0;"><strong>Phone</strong></td>
                        <td style="padding:10px; background:#f9fbff; border:1px solid #d0dff0;">{patient_data['phone']}</td>
                    </tr>
                    <tr>
                        <td style="padding:10px; background:#ffffff; border:1px solid #d0dff0;"><strong>Symptoms / Concern</strong></td>
                        <td style="padding:10px; background:#ffffff; border:1px solid #d0dff0;">{patient_data['concern']}</td>
                    </tr>
                    <tr>
                        <td style="padding:10px; background:#f9fbff; border:1px solid #d0dff0;"><strong>Urgency Level</strong></td>
                        <td style="padding:10px; background:#f9fbff; border:1px solid #d0dff0;">
                            <span style="
                                padding:4px 12px; border-radius:20px; font-weight:bold;
                                background:{'#ffeaea' if patient_data['urgency']=='High' else '#fff7e6' if patient_data['urgency']=='Medium' else '#eafaf1'};
                                color:{'#c0392b' if patient_data['urgency']=='High' else '#e67e22' if patient_data['urgency']=='Medium' else '#27ae60'};
                            ">{patient_data['urgency']}</span>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding:10px; background:#ffffff; border:1px solid #d0dff0;"><strong>Additional Notes</strong></td>
                        <td style="padding:10px; background:#ffffff; border:1px solid #d0dff0;">{patient_data['notes'] or 'None provided'}</td>
                    </tr>
                    <tr>
                        <td style="padding:10px; background:#f9fbff; border:1px solid #d0dff0;"><strong>Submitted At</strong></td>
                        <td style="padding:10px; background:#f9fbff; border:1px solid #d0dff0;">{patient_data['submitted_at']}</td>
                    </tr>
                </table>

                <p style="margin-top:24px; font-size:12px; color:#888;">
                    ⚠️ This is a prototype notification from MyNextStepHealth. 
                    Do not use this system for emergencies.
                </p>
            </div>
        </body>
        </html>
        """

        # Build the email message object
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[MyNextStepHealth] New Intake: {patient_data['full_name']} ({patient_data['urgency']} Urgency)"
        msg["From"]    = EMAIL_ADDRESS
        msg["To"]      = clinic_email
        msg.attach(MIMEText(html_body, "html"))

        # Connect to Gmail's SMTP server and send
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()                              # Encrypt the connection
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)   # Login with app password
            server.sendmail(EMAIL_ADDRESS, clinic_email, msg.as_string())

        print(f"[Email] Notification sent for {patient_data['full_name']}")

    except Exception as e:
        # Don't crash the app if email fails — just log it
        print(f"[Email] Failed to send notification: {e}")




# ─────────────────────────────────────────────
# Contact Form Email
# Uses the same Gmail account as patient notifications.
# ─────────────────────────────────────────────
def send_contact_email(data: dict):
    """Email a website enquiry to CONTACT_TO.
    Reply-To is the visitor, so Reply in Gmail goes back to them."""
    html_body = f"""
    <html>
    <body style="font-family:Arial,sans-serif;color:#1a1a2e;max-width:600px;margin:auto;">
        <div style="background:#1B3A6B;padding:24px;border-radius:8px 8px 0 0;">
            <h2 style="color:#ffffff;margin:0;">&#9993; New Website Enquiry — MyNextStepHealth</h2>
        </div>
        <div style="background:#f4f8ff;padding:24px;border-radius:0 0 8px 8px;border:1px solid #d0dff0;">
            <table style="width:100%;border-collapse:collapse;">
                <tr>
                    <td style="padding:10px;background:#ffffff;border:1px solid #d0dff0;width:35%;"><strong>Name</strong></td>
                    <td style="padding:10px;background:#ffffff;border:1px solid #d0dff0;">{data['name']}</td>
                </tr>
                <tr>
                    <td style="padding:10px;background:#f9fbff;border:1px solid #d0dff0;"><strong>Email</strong></td>
                    <td style="padding:10px;background:#f9fbff;border:1px solid #d0dff0;">{data['email']}</td>
                </tr>
                <tr>
                    <td style="padding:10px;background:#ffffff;border:1px solid #d0dff0;"><strong>Organisation</strong></td>
                    <td style="padding:10px;background:#ffffff;border:1px solid #d0dff0;">{data['organisation'] or 'Not given'}</td>
                </tr>
                <tr>
                    <td style="padding:10px;background:#f9fbff;border:1px solid #d0dff0;"><strong>Subject</strong></td>
                    <td style="padding:10px;background:#f9fbff;border:1px solid #d0dff0;">{data['subject']}</td>
                </tr>
                <tr>
                    <td style="padding:10px;background:#ffffff;border:1px solid #d0dff0;"><strong>Received</strong></td>
                    <td style="padding:10px;background:#ffffff;border:1px solid #d0dff0;">{data['submitted_at']}</td>
                </tr>
            </table>

            <div style="margin-top:18px;padding:16px;background:#ffffff;border:1px solid #d0dff0;border-radius:6px;">
                <strong style="display:block;margin-bottom:8px;">Message</strong>
                <div style="white-space:pre-wrap;color:#333;">{data['message']}</div>
            </div>

            <p style="margin-top:20px;font-size:12px;color:#888;">
                Reply directly to this email to respond to {data['name']}.
            </p>
        </div>
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"]  = f"[MyNextStepHealth] {data['subject']} — {data['name']}"
    msg["From"]     = EMAIL_ADDRESS
    msg["To"]       = CONTACT_TO
    msg["Reply-To"] = data["email"]
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.sendmail(EMAIL_ADDRESS, CONTACT_TO, msg.as_string())

    print(f"[Email] Contact enquiry sent from {data['email']}")
    return True


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────

@app.route("/")
def index():
    """Homepage — clickable MyNextStepHealth banner."""
    return render_template("clickable.html")

@app.route("/")
def clickable():
    return render_template("clickable.html")

@app.route("/intake", methods=["GET", "POST"])
@limiter.limit("5 per hour; 20 per day", methods=["POST"])
def intake():
    """
    Patient intake form.
    GET  → display the blank form
    POST → validate, save to DB, send email, redirect to confirmation
    """
    if request.method == "POST":
        # Pull every field value directly from the submitted form
        clinic_name  = request.form.get("clinic_name", "").strip()
        clinic_email = get_clinic_email(clinic_name)
        full_name    = request.form.get("full_name", "").strip()
        email        = request.form.get("email", "").strip()
        phone        = request.form.get("phone", "").strip()
        concern      = request.form.get("concern", "").strip()
        urgency      = request.form.get("urgency", "").strip()
        notes        = request.form.get("notes", "").strip()
        submitted_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Basic server-side validation — make sure required fields aren't empty
        if not all([clinic_name, full_name, email, phone, concern, urgency]):
            flash("Please fill in all required fields.", "error")
            return redirect(url_for("intake"))

        # Guard against a clinic slug that isn't ours (edited URL, stale link)
        if not clinic_email:
            flash("That clinic was not recognised. Please choose from the list.", "error")
            return redirect(url_for("intake"))

        # Save the submission to SQLite
        conn = get_db()
        conn.execute("""
            INSERT INTO patients
                (clinic_name, full_name, email, phone, concern, urgency, notes, status, submitted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'New', ?)
        """, (clinic_name, full_name, email, phone, concern, urgency, notes, submitted_at))
        conn.commit()
        conn.close()

        # Package data for the email (uses real submitted values, not placeholders)
        patient_data = {
            "clinic_name":  clinic_name,
            "full_name":    full_name,
            "email":        email,
            "phone":        phone,
            "concern":      concern,
            "urgency":      urgency,
            "notes":        notes,
            "submitted_at": submitted_at,
        }
        send_email_notification(patient_data, clinic_email)

        # Redirect to confirmation, remembering which clinic they used
        # so "Submit another" keeps them with the same one.
        return redirect(url_for("confirmation", name=full_name,
                                clinic=clinic_name))

    # ── GET: which clinics should this patient see? ──
    # The banner link on each customer's website carries their ID:
    #   /intake?clinic=oakwood-surgery  -> that one site, pre-selected
    #   /intake?org=riverside           -> only Riverside's sites
    #   /intake                         -> every active clinic
    org_slug    = request.args.get("org", "").strip()
    clinic_slug = request.args.get("clinic", "").strip()
    clinics     = get_clinics(org_slug or None, clinic_slug or None)

    return render_template(
        "intake.html",
        clinics=clinics,
        preselected=clinic_slug if len(clinics) == 1 else "",
    )






@app.route("/contact", methods=["GET", "POST"])
@limiter.limit("3 per hour; 10 per day", methods=["POST"])
def contact():
    """Website contact form. The form itself lives in base.html."""

    # Typing /contact directly goes to the section on the homepage
    if request.method == "GET":
        return redirect(url_for("index") + "#contact")

    # Honeypot: only bots fill this in. Pretend success so they don't learn.
    if request.form.get("website", "").strip():
        flash("Thanks — your message has been sent.", "success")
        return redirect(url_for("index") + "#contact")

    name         = request.form.get("name", "").strip()
    email        = request.form.get("email", "").strip()
    organisation = request.form.get("organisation", "").strip()
    subject      = request.form.get("subject", "").strip()
    message      = request.form.get("message", "").strip()
    submitted_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    errors = []
    if not name:                  errors.append("Please enter your name.")
    if not EMAIL_RE.match(email): errors.append("Please enter a valid email address.")
    if not subject:               errors.append("Please choose what your message is about.")
    if not message:               errors.append("Please write your message.")
    if len(message) > 5000:       errors.append("Please keep your message under 5000 characters.")

    if errors:
        flash(" ".join(errors), "error")
        return render_template("base.html", form_data={
            "name": name, "email": email, "organisation": organisation,
            "subject": subject, "message": message,
        }), 400

    # Save first, so nothing is lost if the email fails
    conn = get_db()
    cur = conn.execute("""
        INSERT INTO contact_messages
            (name, email, organisation, subject, message, submitted_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (name, email, organisation, subject, message, submitted_at))
    conn.commit()
    row_id = cur.lastrowid

    try:
        send_contact_email({
            "name": name, "email": email, "organisation": organisation,
            "subject": subject, "message": message, "submitted_at": submitted_at,
        })
        conn.execute("UPDATE contact_messages SET emailed = 1 WHERE id = ?", (row_id,))
        conn.commit()
    except Exception as e:
        print(f"[Email] Failed to send contact enquiry: {e}")

    conn.close()

    flash("Thanks — your message has been sent. We'll reply within two working days.", "success")
    return redirect(url_for("index") + "#contact")


@app.route("/confirmation")
def confirmation():
    """Thank-you page shown after a successful intake submission."""
    name        = request.args.get("name", "Patient")
    clinic_slug = request.args.get("clinic", "").strip()

    # Look up the clinic's display name so we can tell the patient
    # exactly who received their request.
    clinic_display = None
    if clinic_slug:
        rows = get_clinics(clinic_slug=clinic_slug)
        if rows:
            clinic_display = rows[0]["name"]

    return render_template("confirmation.html",
                           name=name,
                           clinic_slug=clinic_slug,
                           clinic_display=clinic_display)

@app.route('/base')
def base():
    return render_template('base.html')

@app.route("/dashboard")
def dashboard():
    return "Provider dashboard disabled for security.", 403
    """
    Provider dashboard — lists all patient submissions.
    Supports optional filtering by status via ?status=New / In Progress / Complete
    """
    status_filter = request.args.get("status", "all")
    conn = get_db()

    if status_filter == "all":
        patients = conn.execute(
            "SELECT * FROM patients ORDER BY submitted_at DESC"
        ).fetchall()
    else:
        patients = conn.execute(
            "SELECT * FROM patients WHERE status = ? ORDER BY submitted_at DESC",
            (status_filter,)
        ).fetchall()

    # Counts for the summary badges
    counts = conn.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status='New'         THEN 1 ELSE 0 END) AS new_count,
            SUM(CASE WHEN status='In Progress' THEN 1 ELSE 0 END) AS in_progress_count,
            SUM(CASE WHEN status='Complete'    THEN 1 ELSE 0 END) AS complete_count
        FROM patients
    """).fetchone()
    conn.close()

    return render_template(
        "dashboard.html",
        patients=patients,
        counts=counts,
        status_filter=status_filter
    )


@app.route("/patient/<int:patient_id>")
def patient_detail(patient_id):
    return "Patient details disabled for security.", 403
    """View full details for a single patient submission."""
    conn = get_db()
    patient = conn.execute(
        "SELECT * FROM patients WHERE id = ?", (patient_id,)
    ).fetchone()
    conn.close()

    if patient is None:
        flash("Patient record not found.", "error")
        return redirect(url_for("dashboard"))

    return render_template("patient_detail.html", patient=patient)


@app.route("/update_status/<int:patient_id>", methods=["POST"])
def update_status(patient_id):
    """
    Provider action — update the status of a patient submission.
    Called from both the dashboard and the detail page.
    """
    new_status = request.form.get("status")
    valid_statuses = ["New", "In Progress", "Complete"]

    if new_status not in valid_statuses:
        flash("Invalid status value.", "error")
        return redirect(url_for("dashboard"))

    conn = get_db()
    conn.execute(
        "UPDATE patients SET status = ? WHERE id = ?",
        (new_status, patient_id)
    )
    conn.commit()
    conn.close()

    flash(f"Status updated to '{new_status}'.", "success")

    # Return to wherever the provider came from
    referrer = request.form.get("referrer", "dashboard")
    if referrer == "detail":
        return redirect(url_for("patient_detail", patient_id=patient_id))
    return redirect(url_for("dashboard"))


# ─────────────────────────────────────────────
# Error Handlers
# ─────────────────────────────────────────────
@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    """Usually means the page sat open so long the session expired."""
    flash("Your session expired for security reasons. "
          "Please fill in the form again.", "error")
    return redirect(url_for("intake"))


@app.errorhandler(429)
def handle_rate_limit(e):
    """Too many submissions from one address."""
    flash("You have sent several requests recently. Please wait a little "
          "while before sending another. If this is urgent, contact your "
          "clinic by phone.", "error")
    return redirect(url_for("intake")), 429


# ─────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────
if __name__ == "__main__":
    init_db()           # Create DB tables if they don't exist
    print("=" * 50)
    print("  MyNextStepHealth is running!")
    print("  Open: http://127.0.0.1:5000")
    print("=" * 50)
    # debug=False always. With debug on, anyone who triggers an error
    # gets an interactive Python console on your server.
    app.run(debug=False)