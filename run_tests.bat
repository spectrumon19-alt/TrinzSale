@echo off
REM ─────────────────────────────────────────────────────────────────────────────
REM  POS System – Test Runner (Windows)
REM
REM  Usage:
REM    run_tests.bat            Run all tests except slow/UI
REM    run_tests.bat all        Run all tests including slow
REM    run_tests.bat ui         Run Playwright UI tests only (app must be running)
REM    run_tests.bat fast       Run only API + DB tests (no performance, no UI)
REM    run_tests.bat security   Run only security tests
REM    run_tests.bat coverage   Run with coverage report
REM ─────────────────────────────────────────────────────────────────────────────

set PYTHONPATH=%~dp0
set TEST_DB_HOST=localhost
set TEST_DB_NAME=pos_test_db
set TEST_DB_USER=postgres
set TEST_DB_PASSWORD=postgres
set TEST_DB_PORT=5432

if "%1"=="all" (
    python -m pytest tests/ -v --tb=short -m "not ui" ^
        --html=tests/reports/test_report.html --self-contained-html ^
        --cov=routes --cov=auth --cov=db ^
        --cov-report=html:tests/reports/coverage ^
        --cov-report=term-missing
    goto end
)

if "%1"=="ui" (
    python -m pytest tests/ui/ -v --tb=short -m "ui" ^
        --html=tests/reports/ui_report.html --self-contained-html
    goto end
)

if "%1"=="fast" (
    python -m pytest tests/api/ tests/database/ -v --tb=short ^
        --html=tests/reports/fast_report.html --self-contained-html
    goto end
)

if "%1"=="security" (
    python -m pytest tests/security/ -v --tb=short ^
        --html=tests/reports/security_report.html --self-contained-html
    goto end
)

if "%1"=="coverage" (
    python -m pytest tests/ -v --tb=short -m "not ui and not slow" ^
        --cov=routes --cov=auth --cov=db ^
        --cov-report=html:tests/reports/coverage ^
        --cov-report=term-missing ^
        --cov-fail-under=70
    goto end
)

REM Default: all except slow and UI
python -m pytest tests/ -v --tb=short -m "not slow and not ui" ^
    --html=tests/reports/test_report.html --self-contained-html ^
    --cov=routes --cov=auth --cov=db ^
    --cov-report=html:tests/reports/coverage ^
    --cov-report=term-missing

:end
echo.
echo Test reports saved to: tests\reports\
