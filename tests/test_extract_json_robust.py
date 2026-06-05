"""Tests for C3: extract_json_object robustness.

The previous implementation used a greedy regex `r"\\{[\\s\\S]*\\}"` which
broke on multiple JSON objects, braces inside strings, and `}` inside URLs.

The new implementation uses `json.JSONDecoder().raw_decode` to find the first
complete JSON value, correctly handling:
  - Multiple JSON objects in one string
  - Braces inside string literals
  - Braces inside URL strings
  - Markdown code fences
  - Edge cases (empty / non-JSON / broken JSON)
"""
import pytest
from backend.utils.text_utils import extract_json_object


def test_first_of_multiple_json_objects():
    """'{"a":1} {"b":2}' should return the FIRST object, not the concatenation."""
    result = extract_json_object('{"a":1} {"b":2}')
    assert result == {"a":1}, f"Expected first object {{'a':1}}, got {result}"


def test_brace_inside_string():
    """Brace inside a string value should be preserved, not break parsing."""
    result = extract_json_object('{"text":"a}b","c":1}')
    assert result == {"text": "a}b", "c": 1}, f"Got {result}"


def test_brace_inside_url_in_string():
    """A `}` inside a URL string should NOT be treated as JSON end."""
    text = '{"reason":"see https://example.com/}","x":1}'
    result = extract_json_object(text)
    assert result is not None, f"Got None for {text!r}"
    assert result == {"reason": "see https://example.com/}", "x": 1}, f"Got {result}"


def test_markdown_code_block():
    """Markdown ```json ... ``` code fences should be stripped, returning inner JSON."""
    result = extract_json_object('```json\n{"a":1}\n```')
    assert result == {"a": 1}, f"Got {result}"


def test_markdown_code_block_no_lang():
    """Bare ``` ... ``` fences should also work."""
    result = extract_json_object('```\n{"x":42}\n```')
    assert result == {"x": 42}, f"Got {result}"


def test_non_json_returns_none():
    """Non-JSON input should return None, not raise."""
    assert extract_json_object("not json at all") is None
    assert extract_json_object("hello world") is None
    assert extract_json_object("```\nplain text\n```") is None


def test_empty_returns_none():
    """Empty / whitespace-only input should return None."""
    assert extract_json_object("") is None
    assert extract_json_object("   ") is None
    assert extract_json_object("\n\t") is None


def test_broken_json_returns_none():
    """Malformed JSON (e.g., unclosed brace) should return None."""
    assert extract_json_object('{"broken') is None
    assert extract_json_object('{"a":1,') is None
    assert extract_json_object('{') is None
    assert extract_json_object('{"a": 1, "b":}') is None


def test_pure_json_string():
    """A pure JSON object (no surrounding text) should parse."""
    assert extract_json_object('{"a":1}') == {"a": 1}
    assert extract_json_object('{"a":1, "b":[1,2,3]}') == {"a": 1, "b": [1, 2, 3]}


def test_nested_json():
    """Nested JSON should be handled correctly (one full top-level object)."""
    text = '{"outer":{"inner":1,"list":[1,2,3]},"x":42}'
    result = extract_json_object(text)
    assert result == {"outer": {"inner": 1, "list": [1, 2, 3]}, "x": 42}


def test_json_with_surrounding_text():
    """JSON embedded in surrounding prose should be found."""
    text = 'Here is the result: {"status": "ok", "code": 200} and that is all.'
    result = extract_json_object(text)
    assert result == {"status": "ok", "code": 200}


def test_unicode_in_json():
    """Unicode characters inside JSON strings should be preserved."""
    result = extract_json_object('{"name": "中文测试", "emoji": "hello"}')
    assert result == {"name": "中文测试", "emoji": "hello"}


def test_escaped_quote_in_string():
    """Escaped quotes inside string values should be handled."""
    result = extract_json_object(r'{"msg": "He said \"hi\"", "ok": true}')
    assert result == {"msg": 'He said "hi"', "ok": True}
