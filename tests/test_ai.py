import json
import os
import stat

import pytest

from nightcrawler.ai import AI, AIError, ClaudeCodeBackend, resolve_backend


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    """A stand-in `claude` executable that records its env/args and returns structured output."""
    log = tmp_path / "calls.jsonl"
    script = tmp_path / "claude"
    script.write_text(f"""#!/usr/bin/env python3
import json, os, sys
stdin = sys.stdin.read()
with open({str(log)!r}, "a") as fh:
    fh.write(json.dumps({{"args": sys.argv[1:], "stdin": stdin,
        "token": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"), "api_key": os.environ.get("ANTHROPIC_API_KEY")}}) + "\\n")
print(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "result": "",
                  "structured_output": {{"ok": True}}}}))
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    return log


def test_claude_code_backend_uses_subscription_not_api_key(fake_claude, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-should-not-leak")
    backend = ClaudeCodeBackend(model="sonnet", oauth_token="sk-ant-oat-test")
    out = backend.structured("system", "hello", {"type": "object"}, "low")
    assert out == {"ok": True}
    call = json.loads(fake_claude.read_text().splitlines()[0])
    assert call["token"] == "sk-ant-oat-test" and call["api_key"] is None
    assert call["stdin"] == "hello"
    args = call["args"]
    assert args[:3] == ["-p", "--output-format", "json"]
    assert args[args.index("--model") + 1] == "sonnet" and args[args.index("--tools") + 1] == ""


def test_resolve_backend_prefers_subscription(fake_claude, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    b = resolve_backend({"ai_backend": "auto", "ai_oauth_token": "tok", "ai_model": ""})
    assert isinstance(b, ClaudeCodeBackend)
    assert resolve_backend({"ai_backend": "off"}) is None


def test_hourly_limit(fake_claude):
    ai = AI(ClaudeCodeBackend(oauth_token="t"), max_calls_per_hour=1)
    import nightcrawler.ai as mod
    mod._CALL_LOG.clear()
    ai._call("s", "p", {"type": "object"})
    with pytest.raises(AIError, match="limit"):
        ai._call("s", "p", {"type": "object"})
    mod._CALL_LOG.clear()


def test_not_logged_in_gives_setup_hint(tmp_path, monkeypatch):
    script = tmp_path / "claude"
    script.write_text('#!/bin/sh\ncat >/dev/null\necho \'{"type":"result","subtype":"success","is_error":true,'
                      '"result":"Not logged in · Please run /login"}\'\n')
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    with pytest.raises(AIError, match="setup-token"):
        ClaudeCodeBackend().structured("s", "p", {"type": "object"}, "low")
