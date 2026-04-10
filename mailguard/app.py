"""Streamlit web UI for mailguard.

Run locally:     streamlit run mailguard/app.py
Deploy free:     https://share.streamlit.io — connect repo, done.

The UI is designed for non-technical GTM marketers:
 - Drag-drop CSV
 - Auto-detect email column
 - Live progress
 - Downloadable enriched CSV + summary chart
 - No login, no data leaves the server
"""
from __future__ import annotations

import io
import time

import pandas as pd
import plotly.express as px
import streamlit as st

from mailguard import __version__
from mailguard.core import validate_bulk_sync

st.set_page_config(
    page_title="mailguard — bulk email validator",
    page_icon="✉️",
    layout="wide",
)

st.title("✉️ mailguard")
st.caption(
    f"Free, privacy-first bulk email validator · v{__version__} · "
    "No data is stored or shared."
)

with st.sidebar:
    st.header("Options")
    concurrency = st.slider("Concurrency", 10, 200, 50, 10)
    check_smtp = st.checkbox("SMTP probe (slow, may be blocked)", value=False)
    check_catchall = st.checkbox("Catch-all detection", value=False)
    timeout = st.slider("Timeout (seconds)", 3, 30, 10)
    st.markdown("---")
    st.markdown(
        "**Tip:** SMTP probes fail on most cloud hosts (port 25 blocked). "
        "The layered heuristics already give ~85% accuracy without SMTP."
    )
    st.markdown("[⭐ Star on GitHub](https://github.com/mothivenkatesh/mailguard)")

tab_bulk, tab_single, tab_about = st.tabs(["📁 Bulk CSV", "🔍 Single", "ℹ️ About"])

with tab_bulk:
    uploaded = st.file_uploader("Upload a CSV with email addresses", type=["csv"])
    if uploaded:
        try:
            df = pd.read_csv(uploaded, dtype=str, keep_default_na=False)
        except Exception as e:
            st.error(f"Could not read CSV: {e}")
            st.stop()

        st.write(f"**{len(df)}** rows loaded")
        st.dataframe(df.head(5), use_container_width=True)

        # Auto-detect email column
        candidates = [c for c in df.columns if "mail" in c.lower() or "address" in c.lower()]
        default_idx = df.columns.get_loc(candidates[0]) if candidates else 0
        email_col = st.selectbox(
            "Which column contains the email addresses?",
            options=df.columns.tolist(),
            index=int(default_idx),
        )

        if st.button("🚀 Validate all", type="primary"):
            emails = [e.strip() for e in df[email_col].astype(str).tolist() if e.strip()]
            progress = st.progress(0.0, text="Starting...")
            t0 = time.time()

            def cb(done: int, total: int) -> None:
                progress.progress(done / max(total, 1), text=f"{done}/{total} validated")

            results = validate_bulk_sync(
                emails,
                concurrency=concurrency,
                check_smtp=check_smtp,
                check_catchall=check_catchall,
                timeout=timeout,
                progress_cb=cb,
            )
            elapsed = time.time() - t0
            progress.empty()
            st.success(f"Validated {len(results)} emails in {elapsed:.1f}s")

            # Merge results back into dataframe
            res_map = {r.email: r for r in results}
            df["mg_verdict"] = df[email_col].map(
                lambda e: res_map[e.strip()].verdict if e.strip() in res_map else ""
            )
            df["mg_score"] = df[email_col].map(
                lambda e: res_map[e.strip()].score if e.strip() in res_map else ""
            )
            df["mg_reason"] = df[email_col].map(
                lambda e: res_map[e.strip()].reason if e.strip() in res_map else ""
            )
            df["mg_type"] = df[email_col].map(
                lambda e: res_map[e.strip()].email_type if e.strip() in res_map else ""
            )
            df["mg_disposable"] = df[email_col].map(
                lambda e: "yes" if e.strip() in res_map and res_map[e.strip()].disposable else "no"
            )
            df["mg_role"] = df[email_col].map(
                lambda e: "yes" if e.strip() in res_map and res_map[e.strip()].role_based else "no"
            )
            df["mg_typo_suggestion"] = df[email_col].map(
                lambda e: res_map[e.strip()].typo_suggestion or "" if e.strip() in res_map else ""
            )

            # Summary
            col1, col2, col3, col4 = st.columns(4)
            verdict_counts = df["mg_verdict"].value_counts()
            col1.metric("Deliverable", int(verdict_counts.get("deliverable", 0)))
            col2.metric("Risky", int(verdict_counts.get("risky", 0)))
            col3.metric("Undeliverable", int(verdict_counts.get("undeliverable", 0)))
            col4.metric("Speed", f"{len(results)/max(elapsed,0.01):.0f}/s")

            # Chart
            if not verdict_counts.empty:
                fig = px.pie(
                    names=verdict_counts.index,
                    values=verdict_counts.values,
                    color=verdict_counts.index,
                    color_discrete_map={
                        "deliverable": "#22c55e",
                        "risky": "#eab308",
                        "undeliverable": "#ef4444",
                        "unknown": "#9ca3af",
                    },
                    hole=0.4,
                )
                st.plotly_chart(fig, use_container_width=True)

            # Show issues
            typos = df[df["mg_typo_suggestion"] != ""]
            if len(typos) > 0:
                st.warning(f"Found {len(typos)} possible typos — review before discarding")
                st.dataframe(
                    typos[[email_col, "mg_typo_suggestion"]].head(20),
                    use_container_width=True,
                )

            st.dataframe(df, use_container_width=True)
            buf = io.StringIO()
            df.to_csv(buf, index=False)
            st.download_button(
                "⬇️ Download enriched CSV",
                data=buf.getvalue(),
                file_name="validated.csv",
                mime="text/csv",
                type="primary",
            )

with tab_single:
    email = st.text_input("Email address", placeholder="jane.doe@example.com")
    if st.button("Validate") and email:
        from mailguard.core import validate_sync

        r = validate_sync(email, check_smtp=check_smtp, check_catchall=check_catchall)
        verdict_color = {
            "deliverable": "green",
            "risky": "orange",
            "undeliverable": "red",
        }.get(r.verdict, "gray")
        st.markdown(f"### :{verdict_color}[{r.verdict.upper()}] — score {r.score}/100")
        st.json(r.to_dict())

with tab_about:
    st.markdown(
        """
        **mailguard** is an open-source bulk email validator built for GTM marketers
        who need to clean lead lists before sending campaigns — without paying
        per-email fees to ZeroBounce/NeverBounce/Hunter.

        ### Layers
        1. **Syntax** — RFC 5322 / 6531 compliant (Unicode / IDN supported)
        2. **Typo detection** — catches `gmial.com` → `gmail.com`
        3. **Disposable detection** — 800+ known throwaway providers
        4. **Role-based** — flags `info@`, `sales@`, `support@`
        5. **Free vs. work** — personal vs. corporate routing
        6. **DNS / MX resolution** — async, cached
        7. **Catch-all detection** — probes domain with random local part
        8. **SMTP RCPT probe** — optional, fault-tolerant
        9. **Deliverability score** — 0–100 weighted across all signals

        ### Privacy
        Your CSV never leaves this server. Nothing is logged or stored.
        For maximum privacy, self-host with Docker.
        """
    )
