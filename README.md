# Moodle Assignment Automation System

A production-grade, modular, secure, and observable automation system engineered to discover college assignments, analyze instructions, generate solutions, execute programs in isolation, capture genuine code and output screenshots, assemble formatted PDFs, and safely submit files to Moodle.

---

## Architecture Highlights

- **Common Client Abstraction:** Interacts with official Moodle Web Services REST API (`server.php`), with an automatic Playwright browser fallback for SSO/MFA instances.
- **Durable 10-Stage State Machine:**
  `DISCOVERED` ➔ `ELIGIBILITY_CHECK` ➔ `GENERATING` ➔ `EXECUTING` ➔ `CAPTURING` ➔ `PDF_BUILDING` ➔ `PDF_VALIDATING` ➔ `AWAITING_APPROVAL` ➔ `UPLOADING` ➔ `VERIFYING` ➔ `SUBMITTED`.
- **Authentic Execution Verification:** Never fabricates screenshots or claims submission success without authoritative Moodle server verification.
- **Isolated Execution Sandbox:** Scrubbed environment variables (zero credential leakage), process timeouts, and resource bounding.
- **Professional PDF Generation:** Two-pass dynamic page numbering ("Page X of Y"), cover page metadata, aspect-ratio-scaled image embedding, and automated PDF structural validation.
- **Idempotency & Crash Recovery:** SHA-256 fingerprinting prevents duplicate work; startup crash recovery reconciles interrupted tasks.

---

## Repository Structure

```
moodle-automation/
├── app/
│   ├── main.py                  # Rich Typer CLI interface
│   ├── config.py                # Typed Pydantic Settings
│   ├── logging_config.py        # Structured JSON logger with auto-redaction
│   ├── database/                # SQLAlchemy 2.0 ORM models, Repositories, Migrations
│   ├── moodle/                  # API & Playwright browser integration layer
│   ├── discovery/               # Assignment scanner, deadline rules, deduplication
│   ├── generation/              # Solution planner, language handlers, review gating
│   ├── execution/               # Process isolation runner and output validation
│   ├── screenshots/             # Code syntax rendering & terminal output capture
│   ├── documents/               # ReportLab PDF layout builder & PDF validator
│   ├── uploads/                 # Safe uploader & post-upload reconciler
│   ├── jobs/                    # State machine task runner, scheduler, retry policy
│   ├── security/                # Secrets manager, redaction, path traversal sandbox
│   └── monitoring/              # Health checker and operational metrics
├── tests/
│   ├── unit/                    # Comprehensive unit tests for every module
│   ├── integration/             # Full vertical slice test
│   └── load/                    # 100-assignment simulated workload test
├── data/                        # Persistent storage: SQLite DB, PDFs, screenshots
├── Dockerfile                   # Production container definition
├── compose.yaml                 # Multi-container orchestration (PostgreSQL + Redis + App)
├── pyproject.toml               # Dependency specifications & scripts
└── .env.example                 # Environment configuration template
```

---

## Installation & Quickstart

### 1. Local Python Environment

Requires **Python 3.11+** (Tested on Python 3.12 and 3.14).

```bash
# Clone and enter workspace
git clone <repo_url>
cd moodle-automation

# Create virtual environment
python -m venv .venv
# Windows:
.\.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# Install package and dependencies
pip install -e ".[dev]"
```

### 2. Configuration Setup

Copy the example configuration file:

```bash
cp .env.example .env
```

Edit `.env` to configure your Moodle instance and student details:

```ini
MOODLE_BASE_URL=https://moodle.yourcollege.edu
MOODLE_INTEGRATION_MODE=auto # "api" for Web Services token, "browser" for Playwright
MOODLE_API_TOKEN=your_token_if_available
STUDENT_NAME=Aditya Agarwal
STUDENT_UID=STU-2026-ENG
INSTITUTION_NAME=College of Engineering and Technology
TIMEZONE=Asia/Kolkata

# Safety gates (keep false initially)
AUTO_UPLOAD=false
AUTO_FINAL_SUBMIT=false
AUTO_APPROVE=false
```

### 3. Initialize Database

Run database migrations using Alembic:

```bash
alembic upgrade head
```

---

## Command-Line Interface (CLI)

The application provides a CLI via `python -m app.main` or `moodle-auto`:

### Check Moodle Connection
```bash
python -m app.main connect
```

### Discover Assignments
```bash
python -m app.main scan
```

### List Discovered Assignments
```bash
# List all assignments
python -m app.main list

# Filter by overdue assignments
python -m app.main list --filter OVERDUE_UNSUBMITTED
```

### Inspect an Assignment
```bash
python -m app.main view 1
```

### Process an Assignment (Generate Code, Execute & Build PDF)
```bash
python -m app.main process 1
```

### Preview Generated PDF
```bash
python -m app.main preview 1
```

### Manual Approval & Upload
```bash
# Approve submission for upload
python -m app.main approve 1

# Safely upload validated PDF to Moodle
python -m app.main upload 1

# Authoritatively verify submission state
python -m app.main verify 1
```

### System Health & Operational Metrics
```bash
python -m app.main status
```

### Run Continuous Background Scheduler
```bash
python -m app.main scheduler
```

---

## Production Deployment (Docker Compose)

For production deployments with PostgreSQL and Redis:

```bash
# Build and run with Docker Compose
docker compose up -d

# Check service logs
docker compose logs -f app

# Run health check inside container
docker compose exec app python -m app.main status
```

---

## Automated Test Suite

Run the complete automated test suite (48 tests across unit, integration, and load suites):

```bash
pytest -v tests
```

---

## Safety Controls & Academic Integrity

- **Controlled Final Submission:** `AUTO_FINAL_SUBMIT` defaults to `false`. Draft submissions are safely preserved in Moodle for student review before final grading submission.
- **No Fabricated Results:** The execution runner records real exit codes and stdout/stderr from actual program execution. Failed programs are explicitly marked as failed and routed for review.
- **Zero Credential Leaks:** Loggers automatically redact tokens, cookies, and passwords. Subprocesses execute with an isolated, stripped environment.

