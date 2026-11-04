# Security Policy: Moodle Assignment Automation System

## 1. Security Overview

The Moodle Assignment Automation System operates under strict zero-trust principles regarding external input, network communication, credential retention, and program execution.

## 2. Core Security Controls

### 2.1 Credential & Session Protection
- **No Token or Password Logging:** Structured logging automatically redacts tokens (`wstoken`), session IDs (`MoodleSession`), authorization headers, and passwords using pattern-based filters.
- **Session State Isolation:** Playwright browser session states and cookies are stored locally in the restricted `./data/` directory and excluded from version control via `.gitignore`.
- **Environment Scrubbing:** Subprocess execution environments strictly strip all Moodle credentials, tokens, database URLs, and sensitive environment variables before running any code.

### 2.2 Malicious Input & Prompt Injection Protection
- **Untrusted Moodle Input:** Assignment titles, descriptions, and instructor attachments are treated as untrusted text.
- **Command Injection Prevention:** The system never executes shell commands extracted directly from assignment descriptions.
- **Safety Classifier:** Solution planning parses and rejects adversarial directives (e.g. system file deletions, token theft commands, instruction override prompts) and routes the assignment for manual human review.

### 2.3 Sandboxed Execution Isolation
- Subprocesses execute with bounded CPU execution time (`SANDBOX_MAX_EXECUTION_TIME_SECONDS`), output truncation limits (`SANDBOX_MAX_OUTPUT_CHARS`), and in temporary isolated directories.
- SQLite database exercises execute entirely in-memory (`:memory:`).
- Execution runners enforce strict timeouts to terminate hanging, infinite-loop, or rogue processes.

### 2.4 Submission Safety & Academic Integrity
- **Safety Gates Disabled by Default:** `AUTO_UPLOAD=false` and `AUTO_FINAL_SUBMIT=false` prevent accidental, unreviewed, or unauthorized uploads to Moodle.
- **Authoritative Verification:** The system never marks an assignment as submitted until Moodle responds with verified confirmation state.
- **Audit Logging:** Every stage transition, generation, validation, and upload event is immutably logged to the `audit_events` database table.

## 3. Reporting Vulnerabilities

If you discover a security vulnerability or weakness within this codebase, please submit an issue or contact the project security maintainer directly. Do not disclose vulnerabilities in public issue trackers until a patch is available.

