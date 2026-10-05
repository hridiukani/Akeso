"""Tests for converting between our types and the OpenAI format. No network calls.

SimpleNamespace stands in for the SDK's response objects: the conversion code only
reads attributes, so any object with the same attribute names works.
"""

import json
from types import SimpleNamespace as NS
from typing import Any

import pytest

from akeso.llm.groq_provider import (
    _from_openai_response,
    _parse_arguments,
    _to_openai_messages,
    _to_openai_tool,
)
from akeso.llm.types import Message, ToolCall, ToolDefinition, Usage


def fake_response(
    content: str | None = None,
    tool_calls: list[Any] | None = None,
    finish_reason: str = "stop",
    usage: Any = NS(prompt_tokens=10, completion_tokens=5),
) -> NS:
    """Build an object shaped like openai's ChatCompletion."""
    message = NS(content=content, tool_calls=tool_calls)
    return NS(choices=[NS(message=message, finish_reason=finish_reason)], usage=usage)


def fake_tool_call(call_id: str, name: str, arguments: str) -> NS:
    return NS(id=call_id, function=NS(name=name, arguments=arguments))


# --- our types -> OpenAI format ---


def test_system_prompt_becomes_first_message() -> None:
    messages = [Message("user", "Fix the bug"), Message("assistant", "Looking now")]

    assert _to_openai_messages("You fix code.", messages) == [
        {"role": "system", "content": "You fix code."},
        {"role": "user", "content": "Fix the bug"},
        {"role": "assistant", "content": "Looking now"},
    ]


def test_tool_definition_is_wrapped_as_function() -> None:
    schema = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
    tool = ToolDefinition(name="read_file", description="Read a file", input_schema=schema)

    assert _to_openai_tool(tool) == {
        "type": "function",
        "function": {"name": "read_file", "description": "Read a file", "parameters": schema},
    }


# --- OpenAI format -> our types ---


def test_plain_text_reply() -> None:
    result = _from_openai_response(fake_response(content="Four"))

    assert result.text == "Four"
    assert result.tool_calls == []
    assert result.usage == Usage(input_tokens=10, output_tokens=5)
    assert result.stop_reason == "end_turn"


def test_tool_calls_are_parsed() -> None:
    response = fake_response(
        content=None,  # tool-only replies often have no text
        tool_calls=[
            fake_tool_call("call_1", "read_file", '{"path": "src/app.py"}'),
            fake_tool_call("call_2", "run_tests", ""),
        ],
        finish_reason="tool_calls",
    )

    result = _from_openai_response(response)

    assert result.text == ""
    assert result.tool_calls == [
        ToolCall(id="call_1", name="read_file", arguments={"path": "src/app.py"}),
        ToolCall(id="call_2", name="run_tests", arguments={}),
    ]
    assert result.stop_reason == "tool_use"


@pytest.mark.parametrize(
    ("finish_reason", "expected"),
    [("stop", "end_turn"), ("tool_calls", "tool_use"), ("length", "max_tokens"), ("content_filter", "other")],
)
def test_stop_reason_mapping(finish_reason: str, expected: str) -> None:
    assert _from_openai_response(fake_response(content="x", finish_reason=finish_reason)).stop_reason == expected


def test_missing_usage_counts_as_zero() -> None:
    result = _from_openai_response(fake_response(content="x", usage=None))

    assert result.usage == Usage(input_tokens=0, output_tokens=0)


# --- tool argument parsing ---


@pytest.mark.parametrize("raw", [None, "", "null"])
def test_empty_arguments_become_empty_dict(raw: str | None) -> None:
    assert _parse_arguments("run_tests", raw) == {}


def test_invalid_json_arguments_raise_with_tool_name() -> None:
    with pytest.raises(ValueError, match="read_file"):
        _parse_arguments("read_file", '{"path": ')


def test_non_object_arguments_raise() -> None:
    with pytest.raises(ValueError, match="non-object"):
        _parse_arguments("read_file", '["a.py"]')


# --- multi-turn tool-use conversations ---


def test_multi_turn_conversation_with_several_tool_calls() -> None:
    read = ToolCall("call_1", "read_file", {"path": "src/stats.py"})
    checks = ToolCall("call_2", "run_checks", {})
    edit = ToolCall("call_3", "apply_edit", {"path": "src/stats.py", "old_str": "- 1", "new_str": ""})
    conversation = [
        Message.user("Fix the failing test."),
        Message.assistant("I'll look first.", [read, checks]),
        Message.tool_result("call_1", "def mean(n): ..."),
        Message.tool_result("call_2", "FAILED: pytest exited with code 1."),
        Message.assistant("", [edit]),
        Message.tool_result("call_3", "Error: old_str was not found in src/stats.py.", is_error=True),
        Message.assistant("I could not apply the edit."),
    ]

    converted = _to_openai_messages("You fix code.", conversation)

    assert converted == [
        {"role": "system", "content": "You fix code."},
        {"role": "user", "content": "Fix the failing test."},
        {
            "role": "assistant",
            "content": "I'll look first.",
            "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "src/stats.py"}'}},
                {"id": "call_2", "type": "function", "function": {"name": "run_checks", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "def mean(n): ..."},
        {"role": "tool", "tool_call_id": "call_2", "content": "FAILED: pytest exited with code 1."},
        {
            "role": "assistant",
            "content": None,  # no text alongside the tool call
            "tool_calls": [
                {
                    "id": "call_3",
                    "type": "function",
                    "function": {"name": "apply_edit", "arguments": '{"path": "src/stats.py", "old_str": "- 1", "new_str": ""}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_3", "content": "Error: old_str was not found in src/stats.py."},
        {"role": "assistant", "content": "I could not apply the edit."},
    ]


def test_response_round_trips_into_history() -> None:
    # A tool-calling reply from the API, turned into our message and sent back again,
    # must keep the same ids, names and arguments.
    # JSON escapes for a non-ASCII character, a newline and quotes, as the API sends them.
    arguments = r'{"path": "src/caf\u00e9.py", "old_str": "a\nb", "new_str": "\"q\""}'
    response = fake_response(
        content=None,
        tool_calls=[fake_tool_call("call_9", "apply_edit", arguments)],
        finish_reason="tool_calls",
    )

    message = _from_openai_response(response).as_message()
    sent_back = _to_openai_messages("sys", [message])[1]

    call = sent_back["tool_calls"][0]
    assert call["id"] == "call_9"
    assert call["function"]["name"] == "apply_edit"
    assert json.loads(call["function"]["arguments"]) == json.loads(arguments)


def test_tool_message_requires_its_call_id() -> None:
    with pytest.raises(ValueError, match="tool_call_id"):
        Message("tool", "result without an id")
