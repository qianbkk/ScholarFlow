"""
VULN-004: Scrub sensitive credentials from logs and error messages.

Patterns covered:
- Anthropic API keys: sk-ant-...
- OpenAI API keys: sk-... (with project form: sk-proj-...)
- DeepSeek API keys: sk-...
- Generic Bearer tokens in Authorization headers
- MiniMax API keys: eyJ... (JWT) longer than 80 chars
"""
import re

_PATTERNS = [
    # Anthropic (sk-ant-api03-...) and OpenAI project (sk-proj-...) and OpenAI legacy (sk-...)
    (re.compile(r'sk-(?:ant-|proj-)?[A-Za-z0-9_\-]{16,}'), 'sk-***'),
    # JWT-style tokens (e.g., MiniMax uses eyJhbGci... format)
    (re.compile(r'eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}'), 'eyJ***.***'),
    # Bearer <token>
    (re.compile(r'(?i)(Bearer\s+)[A-Za-z0-9_\-\.]{16,}'), r'\1***'),
    # x-api-key: <value> (header form)
    (re.compile(r'(?i)(x-api-key["\s:=]+)[A-Za-z0-9_\-\.]{16,}'), r'\1***'),
    # Authorization: <scheme> <token>
    (re.compile(r'(?i)(Authorization["\s:=]+(?:\w+\s+)?)[A-Za-z0-9_\-\.]{16,}'), r'\1***'),
]


def scrub_sensitive(text: str | None, max_len: int = 500) -> str:
    """Replace any sensitive credential patterns in text with redaction markers.

    Truncates to max_len to prevent huge error blobs from filling logs.
    """
    if not text:
        return ''
    out = str(text)
    for pat, repl in _PATTERNS:
        out = pat.sub(repl, out)
    if len(out) > max_len:
        out = out[:max_len] + '...[truncated]'
    return out


def scrub_dict(d: dict | None) -> dict:
    """Recursively scrub all string values in a dict (in-place safe via copy)."""
    if not d:
        return {}
    out = {}
    for k, v in d.items():
        if isinstance(v, str):
            out[k] = scrub_sensitive(v)
        elif isinstance(v, dict):
            out[k] = scrub_dict(v)
        elif isinstance(v, list):
            out[k] = [scrub_sensitive(x) if isinstance(x, str) else x for x in v]
        else:
            out[k] = v
    return out
