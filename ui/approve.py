"""AccuPaid approval queue UI. Run: streamlit run ui/approve.py"""
import requests
import streamlit as st

BASE = "http://localhost:8000"

st.title("AccuPaid — Approval Queue")

query = st.text_input("Hinglish query", placeholder="meri sallery me jyada LOP kata...")
if st.button("Send"):
    if not query.strip():
        st.warning("Type a query first.")
    else:
        try:
            r = requests.post(f"{BASE}/chat", json={"query": query}, timeout=30)
            r.raise_for_status()
            st.session_state["last"] = r.json()
        except requests.RequestException as e:
            st.error(f"chat failed: {e}")

last = st.session_state.get("last")
if last:
    st.subheader(f"run {last.get('run_id')} — {last.get('status')}")
    if last.get("status") == "needs_approval":
        st.warning("Needs approval: " + ", ".join(last.get("reasons", [])))
        reason = st.text_input("Reason / annotation", key="reason")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Approve"):
                try:
                    payload = {"verdict": "approve", "reason": reason,
                               "signature": last["approve_signature"]}
                    r = requests.post(f"{BASE}/approve/{last['run_id']}", json=payload, timeout=30)
                    r.raise_for_status()
                    st.json(r.json().get("result", r.json()))
                except requests.RequestException as e:
                    st.error(f"approve failed: {e}")
        with c2:
            if st.button("Reject"):
                try:
                    payload = {"verdict": "reject", "reason": reason or "rejected in UI",
                               "signature": last["reject_signature"]}
                    r = requests.post(f"{BASE}/approve/{last['run_id']}", json=payload, timeout=30)
                    r.raise_for_status()
                    st.json(r.json().get("result", r.json()))
                except requests.RequestException as e:
                    st.error(f"reject failed: {e}")
    else:
        st.json(last.get("result", last))
        cites = (last.get("result") or {}).get("cites") or []
        if cites:
            st.caption("Cites: " + "; ".join(cites))

st.sidebar.header("Run lookup / auditor export")
lookup = st.sidebar.text_input("run_id")
if st.sidebar.button("Lookup"):
    try:
        r = requests.get(f"{BASE}/runs/{lookup}", timeout=15)
        r.raise_for_status()
        st.sidebar.json(r.json().get("state", r.json()))
    except requests.RequestException as e:
        st.error(f"lookup failed: {e}")
if st.sidebar.button("Auditor export (CSV)"):
    try:
        r = requests.get(f"{BASE}/runs/{lookup}/audit", params={"format": "csv"}, timeout=15)
        r.raise_for_status()
        st.sidebar.download_button("Download audit CSV", r.json().get("csv", ""),
                                   f"{lookup}_audit.csv", "text/csv")
    except requests.RequestException as e:
        st.error(f"audit export failed: {e}")
