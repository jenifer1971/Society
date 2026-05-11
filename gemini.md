# SonarQube Fixer — Project Configuration

## Project Identifiers
sonar_frontend_id: YOUR_FRONTEND_PROJECT_KEY
sonar_backend_id: YOUR_BACKEND_PROJECT_KEY

## Local Paths (relative to repo root, or absolute)
frontend_path: ./frontend
backend_path: ./backend

## Optional Branch Names (omit or leave blank to scan default branch)
frontend_branch:
backend_branch:

## Severity Filter
# Leave blank to fix ALL severities (BLOCKER, CRITICAL, MAJOR, MINOR, INFO).
# Specify one or more comma-separated values to restrict the loop to those only.
# Valid values: BLOCKER, CRITICAL, MAJOR, MINOR, INFO
# Examples:
#   severity_filter: BLOCKER
#   severity_filter: BLOCKER,CRITICAL
#   severity_filter:            ← fixes everything
severity_filter:

## Test Control
# Set to true to skip running tests after each fix pass (speeds up loops).
skip_tests: false

## Sonar-ESLint
# Set to true to run ESLint with the SonarQube ruleset after the fix loop ends.
run_sonar_eslint: true
