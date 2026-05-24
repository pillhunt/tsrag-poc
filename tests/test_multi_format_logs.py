"""Tests for multi-format log parsing (punct B)."""

from incident_intent.error_classifier import classify_error_line, infer_log_kind
from incident_intent.http_access_parsers import parse_http_access_line
from incident_intent.log_discovery import is_log_filename
from incident_intent.timestamp_parsers import parse_log_timestamp


def test_is_log_filename_extended():
    assert is_log_filename("ERRORLOG")
    assert is_log_filename("u_ex230501.log")
    assert is_log_filename("postgresql-2026-05-15.log")
    assert is_log_filename("SQLAGENT.OUT")


def test_classify_mssql_deadlock():
    text = "2026-05-15 14:00:01.12 spid52 Error: 1205 deadlock victim"
    result = classify_error_line(text, file_path="MSSQL/ERRORLOG")
    assert result == ("mssql", "sql_deadlock")


def test_classify_nginx_upstream():
    text = "2026/05/15 14:00:01 [error] upstream timed out while reading response"
    result = classify_error_line(text, file_path="nginx/error.log")
    assert result == ("nginx", "nginx_upstream_timeout")


def test_classify_postgres_timeout():
    text = "2026-05-15 14:00:01 UTC ERROR: canceling statement due to statement timeout"
    result = classify_error_line(text, file_path="pg_log/postgresql-2026-05-15.log")
    assert result == ("postgres", "pg_statement_timeout")


def test_parse_caseone_middleware():
    line = (
        "2026-05-15 14:00:00.123 ; POST ; /api/reports/run ; user ; 360000 ;"
    )
    parsed = parse_http_access_line(
        line,
        source_file="host/RequestLoggingMiddleware.log",
        line_number=1,
    )
    assert parsed is not None
    assert parsed.method == "POST"
    assert parsed.path == "/api/reports/run"
    assert parsed.duration_ms == 360000
    assert parsed.log_format == "caseone_middleware"


def test_parse_nginx_combined():
    line = (
        '127.0.0.1 - - [15/May/2026:14:00:01 +0300] "GET /reports HTTP/1.1" '
        "200 1234 rt=125.500"
    )
    parsed = parse_http_access_line(line, source_file="nginx/access.log", line_number=1)
    assert parsed is not None
    assert parsed.duration_ms == 125500
    assert parsed.log_format == "nginx_combined"


def test_infer_log_kind():
    assert infer_log_kind("nginx/error.log") == "web"
    assert infer_log_kind("MSSQL/ERRORLOG") == "db"
    assert infer_log_kind("app/global.log") == "app"


def test_parse_nginx_timestamp():
    line = '[15/May/2026:14:00:01 +0300] "GET /x HTTP/1.1"'
    ts = parse_log_timestamp(line)
    assert ts is not None
    assert ts.year == 2026
    assert ts.month == 5
