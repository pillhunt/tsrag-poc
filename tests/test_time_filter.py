"""Tests for time filter (point F)."""

from incident_intent.log_scan import TimeSliceFilter, line_in_time_window
from incident_intent.time_pattern_factory import enrich_log_search_patterns, patterns_for_window
from incident_intent.time_window_bounds import datetime_window_bounds
from incident_intent.timestamp_parsers import detect_timestamp_format, parse_log_timestamp
from incident_intent.timestamp_probe import probe_file_format


def test_patterns_for_window_nginx():
    pats = patterns_for_window("2026-04-23", "20:00", "21:00", ["iso_space", "nginx"])
    assert "2026-04-23 20:" in pats
    assert "[23/Apr/2026:20:" in pats


def test_enrich_merges_llm_and_factory():
    merged, warnings = enrich_log_search_patterns(
        "2026-05-15",
        "14:00",
        "15:00",
        ["2026-05-15 14:"],
        ("iso_space", "nginx", "eu_dot"),
    )
    assert "2026-05-15 14:" in merged
    assert any("nginx" in p or "May" in p for p in merged)
    assert not warnings or "лимита" not in warnings[0]


def test_line_in_time_window_nginx_auto():
    line = '127.0.0.1 - - [23/Apr/2026:20:15:30 +0300] "GET /x HTTP/1.1" 200 1'
    bounds = datetime_window_bounds("2026-04-23", "20:00", "21:00")
    assert bounds is not None
    flt = TimeSliceFilter(
        patterns=tuple(),
        window_start=bounds[0],
        window_end=bounds[1],
        strategy="auto",
    )
    assert line_in_time_window(line, file_path="nginx/access.log", flt=flt)


def test_line_in_time_window_grep_nginx_pattern():
    line = '127.0.0.1 - - [23/Apr/2026:20:15:30 +0300] "GET /x HTTP/1.1" 200 1'
    flt = TimeSliceFilter(
        patterns=("[23/Apr/2026:20:",),
        strategy="grep",
    )
    assert line_in_time_window(line, file_path="nginx/access.log", flt=flt)


def test_detect_and_probe_nginx():
    line = '[23/Apr/2026:20:15:30 +0300] "GET / HTTP/1.1"'
    assert detect_timestamp_format(line) == "nginx"
    fmt = probe_file_format("nginx/access.log", [line, line])
    assert fmt == "nginx"


def test_eu_dot_parse():
    line = "23.04.2026 20:15:30.123 something"
    assert detect_timestamp_format(line) == "eu_dot"
    ts = parse_log_timestamp(line)
    assert ts is not None
    assert ts.hour == 20
