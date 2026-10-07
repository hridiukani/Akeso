"""Tests for the versioned agent prompts."""

from akeso.prompts import AGENT_PROMPT_VERSION, AGENT_SYSTEM_PROMPT, SQL_SYSTEM_PROMPT, build_sql_first_message, system_prompt


def test_sql_prompt_and_first_message() -> None:
    assert AGENT_PROMPT_VERSION == "agent-v4"
    assert system_prompt("code") == AGENT_SYSTEM_PROMPT and system_prompt("sql") == SQL_SYSTEM_PROMPT
    for phrase in ("solution.sql", "/akeso/run_query.py", "hidden database", "never date('now')", "never shows the expected values"):
        assert phrase in SQL_SYSTEM_PROMPT

    message = build_sql_first_message("Revenue rules.", "Total revenue?", "2026-06-30", "CREATE TABLE t (x);", "rules here", "FAILED")
    assert "Question: Total revenue?\nAs of: 2026-06-30" in message
    assert "You may only change: solution.sql" in message
    assert "### Database schema (SQLite)\nCREATE TABLE t (x);" in message
    assert message.endswith("### Current check (failing)\nFAILED")
