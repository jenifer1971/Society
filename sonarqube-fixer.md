---
name: sonarqube-fixer
description: Resolves SonarQube issues using the Web API and local gemini.md config. Loops until zero pending issues remain, then validates with sonar-eslint.
---

# SonarQube Multi-Project Fixer

## 0. Argument Parsing

The skill may be invoked with an optional severity argument:

* `/sonarqube-fixer` → fix all severities
* `/sonarqube-fixer BLOCKER` → fix only BLOCKER
* `/sonarqube-fixer BLOCKER,CRITICAL` → fix only those severities

If an argument is provided it overrides `severity_filter` in `gemini.md`.

---

## 1. Discovery Phase

**Fetches metadata needed for the skill.**

1. **Load Metadata**: Read `gemini.md` in the current directory.
2. **Identify Fields**:
   * `sonar_frontend_id` → Frontend project key (skip project if blank).
   * `sonar_backend_id` → Backend project key (skip project if blank).
   * `frontend_path` → Local path for the frontend project.
   * `backend_path` → Local path for the backend project.
   * `frontend_branch` → Optional SonarQube branch for frontend.
   * `backend_branch` → Optional SonarQube branch for backend.
   * `severity_filter` → Comma-separated severities to target (blank = all).
   * `skip_tests` → `true` skips unit test runs inside the loop.
   * `run_sonar_eslint` → `true` runs sonar-eslint after the fix loop ends.
3. **Resolve Severity**: CLI argument → `severity_filter` in `gemini.md` → fallback default `BLOCKER,CRITICAL,MAJOR,MINOR,INFO`.
4. **Environment Check**: Confirm `$SONAR_TOKEN` is set. Abort with a clear message if missing.

---

## 2. Execution Phase

**Fetches the issues from SonarQube (filtered by the category the user specified).**

Build the search URL for the project:

```
BASE = https://sonarqube-ri.vnet.valeo.com/api/issues/search
URL  = {BASE}?componentKeys={PROJECT_KEY}
            &statuses=OPEN,CONFIRMED
            &severities={RESOLVED_SEVERITIES}
            &ps=500
```

Append `&branch={BRANCH}` when a branch is configured in `gemini.md`.

Run the request using PowerShell:

```powershell
$token = $env:SONAR_TOKEN
$resp  = curl.exe -s -u "${token}:" "{URL}"
```

* Parse `.total` from the JSON response → this is the **pending issue count**.
* Paginate using `&p=2`, `&p=3` … when `total > 500` to collect all issues.
* Store the flat list of issues for the Application Phase.

---

## 3. Application Phase

**Fixes the issues found.**

For each issue in the collected list:

1. Extract `message`, `component` (file path), `line`, and `rule` from the JSON.
2. Navigate to the file inside `frontend_path` or `backend_path`.
3. Read the file content around the reported line.
4. Apply the minimal correct fix for the rule violation.
5. Save the file.

> **Note:** Only issues matching the resolved severity filter are fixed. Issues outside the filter are left untouched.

---

## 4. Verification Phase

**Runs `.\build.bat` to make sure the code compiles.**
**Runs unit tests *(optional based on project metadata)*.**
**Addresses issues if found.**

### 4a. Build Check

* **Frontend**: Run `nvm use 20.19` then `.\build.bat`.
* **Backend**: Run `./mvnw compile -q` (skip if no Maven wrapper is present).

If the build **fails**:

* Revert the last edit that caused the failure.
* Log the issue as *"skipped — build error"*.
* Continue to the next issue.

### 4b. Unit Tests *(skipped when `skip_tests: true` in `gemini.md`)*

* **Frontend**: `npm test -- --watchAll=false`
* **Backend**: `./mvnw test -q`

If tests **fail**:

* Revert the last edit that caused the failure.
* Log the issue as *"skipped — test failure"*.
* Continue to the next issue.

---

## 5. Loop Control Phase

**Repeats the Execution → Application → Verification cycle until pending issues reach zero.**

```
PASS = 1

WHILE pending_count > 0:
    Print: "--- Pass {PASS} | {PROJECT_KEY} | Pending: {pending_count} ---"
    → Run Execution Phase    (re-fetch current open issues)
    → Run Application Phase  (apply fixes)
    → Run Verification Phase (build + optional tests)
    → Re-fetch pending_count using &ps=1 for a lightweight count check

    PASS += 1

    Safety cap: if PASS > 20 and pending_count > 0:
        Break and report:
        "Loop cap reached — {pending_count} issues remain. Manual review required."
```

---

## 6. Sonar-ESLint Validation Phase

**Runs only when `run_sonar_eslint: true` in `gemini.md`.**
**Ensures no new lint issues were introduced by the generated fixes.**

### Frontend

```powershell
cd {frontend_path}
nvm use 20.19
npx eslint . --ext .js,.jsx,.ts,.tsx --max-warnings 0
```

### Backend

```bash
cd {backend_path}
./mvnw sonar:sonar \
  -Dsonar.host.url=https://sonarqube-ri.vnet.valeo.com \
  -Dsonar.login=$SONAR_TOKEN --batch-mode -q
```

If new issues are reported:

* Fix them immediately (no loop needed — treat as a final patch pass).
* Re-run the linter or scanner once more to confirm clean before moving on.

---

## 7. Summarization Phase

**Gives a brief summary of issues fixed.**

```
╔══════════════════════════════════════════════════════════╗
║  SonarQube Fix Summary                                   ║
╠══════════════╦══════════╦══════════╦═════════════════════╣
║ Project      ║ Starting ║ Fixed    ║ Remaining           ║
╠══════════════╬══════════╬══════════╬═════════════════════╣
║ Frontend     ║   42     ║   42     ║    0  ✓             ║
║ Backend      ║   17     ║   15     ║    2  ⚠ (cap hit)  ║
╚══════════════╩══════════╩══════════╩═════════════════════╝

Severity filter applied : BLOCKER, CRITICAL
Sonar-ESLint            : PASSED (0 warnings)
Total loop passes       : Frontend ×3  |  Backend ×2
Skipped (build errors)  : 2 issues
Skipped (test failures) : 0 issues
```

**Legend:** ✓ fully resolved · ⚠ loop cap reached · ✗ blocked by errors
