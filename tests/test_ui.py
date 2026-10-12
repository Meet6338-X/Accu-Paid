"""PR8 gates: ChatOps signed-button roundtrip, forgery/expiry rejection, formatting."""

import os
import sys
import time
from urllib.parse import parse_qs, urlparse

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.chatops import build_approve_buttons, format_result_message, parse_button_click

SECRET = "chatops-test-secret"


def _params(url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def test_button_roundtrip():
    urls = build_approve_buttons("run-1", SECRET)
    run_id, verdict = parse_button_click(_params(urls["approve_url"]), SECRET)
    assert (run_id, verdict) == ("run-1", "approve")
    run_id, verdict = parse_button_click(_params(urls["reject_url"]), SECRET)
    assert (run_id, verdict) == ("run-1", "reject")


def test_forged_and_missing_rejected():
    urls = build_approve_buttons("run-2", SECRET)
    bad = _params(urls["approve_url"])
    bad["signature"] = "forged"
    with pytest.raises(PermissionError):
        parse_button_click(bad, SECRET)
    with pytest.raises(PermissionError):
        parse_button_click({"run_id": "run-2"}, SECRET)


def test_expired_rejected():
    urls = build_approve_buttons("run-3", SECRET)
    p = _params(urls["approve_url"])
    p["signature"] = __import__("mcp_server.guards", fromlist=["sign_approval"]).sign_approval(
        "run-3", "approve", "", SECRET, int(time.time()) - 3600)
    with pytest.raises(PermissionError):
        parse_button_click(p, SECRET, ttl=900)


def test_format_message_with_cites():
    msg = format_result_message({"status": "answered", "route": "payroll",
                                 "summary": "net diff 4200",
                                 "cites": ["[tds:04]", "[overtime:05]"]})
    assert "answered" in msg and "[tds:04]" in msg


def test_react_console_present_and_streamlit_gone():
    import json

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert not os.path.exists(os.path.join(root, "ui", "approve.py"))
    pkg = json.load(open(os.path.join(root, "frontend", "package.json"), encoding="utf-8"))
    assert pkg["dependencies"]["react"] and pkg["devDependencies"]["vite"]
    for f in ("index.html", "vite.config.js", "src/main.jsx", "src/App.jsx",
              "src/api.js", "src/Chat.jsx", "src/Runs.jsx", "src/Ingest.jsx",
              "src/Health.jsx", "src/styles.css"):
        assert os.path.exists(os.path.join(root, "frontend", f)), f
    req = open(os.path.join(root, "requirements.txt"), encoding="utf-8").read()
    assert "streamlit" not in req
