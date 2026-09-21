"""Minimal import vertical slice. Business logic remains in application services."""

from __future__ import annotations

import os
import sqlite3

os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")


def main() -> None:
    import streamlit as st

    from family_finance.services import ImportService, PreviewStaleError

    st.set_page_config(page_title="Family Finance", layout="wide")
    st.title("Family Finance")
    st.caption("Local FamilyBiz import review")
    service = ImportService()

    upload = st.file_uploader("Upload a FamilyBiz XLSX export", type=["xlsx"])
    if upload is not None:
        file_bytes = upload.getvalue()
        if st.button("Inspect and preview", type="primary"):
            try:
                preview = service.preview_import(file_bytes, upload.name)
                st.session_state["family_finance_preview"] = preview.model_dump(mode="json")
                st.session_state["family_finance_file"] = file_bytes
                st.session_state["family_finance_filename"] = upload.name
            except (ValueError, OSError, sqlite3.Error) as exc:
                st.error(str(exc))

    preview_data = st.session_state.get("family_finance_preview")
    if preview_data:
        inspection = preview_data["inspection"]
        st.subheader("Preview")
        cols = st.columns(5)
        cols[0].metric("Rows", inspection["transaction_count"])
        cols[1].metric("Sections", inspection["section_count"])
        cols[2].metric("Warnings", preview_data["warning_count"])
        cols[3].metric("Currencies", ", ".join(inspection["currencies"]))
        cols[4].metric("Latest booking date", inspection["max_booking_date"] or "Unavailable")
        if inspection["report_end"] and inspection["max_booking_date"] != inspection["report_end"]:
            st.warning(
                "The source report end date is later than the latest transaction date. "
                "Freshness uses the latest transaction date."
            )
        st.json(
            {
                "issue_counts": preview_data["issue_counts"],
                "sample": preview_data["preview_rows"][:10],
            }
        )
        if st.button("Commit import"):
            try:
                result = service.commit_import(
                    st.session_state["family_finance_file"],
                    preview_data["preview_token"],
                    st.session_state.get("family_finance_filename"),
                )
                st.success(
                    f"{result.status.value}: {result.statistics.model_dump(mode='json')}"
                )
                st.session_state.pop("family_finance_preview", None)
            except PreviewStaleError as exc:
                st.error(f"Preview is stale. {exc}")
            except (ValueError, OSError, sqlite3.Error) as exc:
                st.error(str(exc))

    st.subheader("Import history")
    history = service.history()
    if history:
        st.dataframe(history, use_container_width=True)
    else:
        st.info("No imports have been committed.")

    st.subheader("Unresolved reconciliation cases")
    cases = service.reconciliation_cases()
    if cases:
        for case in cases:
            st.markdown(
                f"**Case {case['id']}** · source row {case['source_record_id']} · "
                f"{case['reason']}"
            )
            st.json({"incoming": case["source"], "candidates": case["candidates"]})
            resolution_labels = ["Accept as new", "Dismiss"]
            resolution_labels.extend(
                f"Link to transaction {candidate['id']} "
                f"({candidate['booking_date']}, {candidate['amount']} {candidate['currency']})"
                for candidate in case["candidates"]
            )
            selection = st.selectbox(
                "Resolution",
                resolution_labels,
                key=f"reconciliation-resolution-{case['id']}",
            )
            if st.button("Apply resolution", key=f"reconciliation-apply-{case['id']}"):
                if selection == "Accept as new":
                    decision = {"resolution": "accept_as_new"}
                elif selection == "Dismiss":
                    decision = {"resolution": "dismiss"}
                else:
                    transaction_id = next(
                        candidate["id"]
                        for candidate in case["candidates"]
                        if selection.startswith(f"Link to transaction {candidate['id']} ")
                    )
                    decision = {
                        "resolution": "link_existing",
                        "transaction_id": transaction_id,
                    }
                try:
                    result = service.resolve_reconciliation(case["id"], decision)
                    st.success(f"Case resolved: {result.status.value}")
                    st.rerun()
                except (ValueError, OSError, sqlite3.Error) as exc:
                    st.error(str(exc))
    else:
        st.info("No open reconciliation cases.")
