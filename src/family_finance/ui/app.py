"""Minimal import vertical slice. Business logic remains in application services."""

from __future__ import annotations

import os

os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")


def main() -> None:
    import streamlit as st
    from sqlalchemy.exc import SQLAlchemyError

    from family_finance.models import EconomicClass, ExpenseBehavior
    from family_finance.services import ImportService, PreviewStaleError

    st.set_page_config(page_title="Family Finance", layout="wide")
    st.title("Family Finance")
    st.caption("Local FamilyBiz import review")
    service = ImportService()
    classifier = service.classification_service
    metrics_service = service.metrics_service

    upload = st.file_uploader("Upload a FamilyBiz XLSX export", type=["xlsx"])
    if upload is not None:
        file_bytes = upload.getvalue()
        if st.button("Inspect and preview", type="primary"):
            try:
                preview = service.preview_import(file_bytes, upload.name)
                st.session_state["family_finance_preview"] = preview.model_dump(mode="json")
                st.session_state["family_finance_file"] = file_bytes
                st.session_state["family_finance_filename"] = upload.name
            except (ValueError, OSError, SQLAlchemyError) as exc:
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
            except (ValueError, OSError, SQLAlchemyError) as exc:
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
                except (ValueError, OSError, SQLAlchemyError) as exc:
                    st.error(str(exc))
    else:
        st.info("No open reconciliation cases.")

    st.divider()
    review_tab, metrics_tab = st.tabs(["Classification review", "Monthly metrics"])
    with review_tab:
        st.subheader("Classification review queue")
        filter_cols = st.columns(6)
        review_month = filter_cols[0].text_input("Month", placeholder="YYYY-MM")
        review_account = filter_cols[1].text_input("Account kind")
        review_currency = filter_cols[2].text_input("Currency", value="ILS")
        review_issue = filter_cols[3].text_input("Issue code")
        review_class = filter_cols[4].selectbox(
            "Economic class", ["(all)"] + [value.value for value in EconomicClass]
        )
        review_source = filter_cols[5].selectbox(
            "Classification source",
            ["(all)", "override", "reusable_rule", "builtin_rule", "unclassified"],
        )
        show_resolved = st.checkbox("Show classified rows", value=False)
        month_value = None
        if review_month:
            try:
                month_value = __import__("datetime").date.fromisoformat(f"{review_month}-01")
            except ValueError:
                st.warning("Month must use YYYY-MM.")
        queue = classifier.review_queue(
            month=month_value,
            account_kind=review_account or None,
            currency=review_currency or None,
            issue=review_issue or None,
            economic_class=None if review_class == "(all)" else review_class,
            classification_source=None if review_source == "(all)" else review_source,
            include_resolved=show_resolved,
        )
        st.caption(f"{len(queue)} item(s) require review")
        for item in queue:
            with st.expander(
                f"Transaction {item.transaction_id} · {item.booking_date} · "
                f"{item.amount} {item.currency} · {item.effective_classification.economic_class.value}"
            ):
                st.json(
                    {
                        "source_fields": item.source_fields,
                        "effective_classification": item.effective_classification.model_dump(mode="json"),
                        "issues": [issue.model_dump(mode="json") for issue in item.issues],
                    }
                )
                form_cols = st.columns(3)
                selected_class = form_cols[0].selectbox(
                    "Economic class",
                    [value.value for value in EconomicClass],
                    index=[value.value for value in EconomicClass].index(
                        item.effective_classification.economic_class.value
                    ),
                    key=f"class-{item.transaction_id}",
                )
                selected_category = form_cols[1].text_input(
                    "Analysis category",
                    value=item.effective_classification.analysis_category or "",
                    key=f"category-{item.transaction_id}",
                )
                selected_behavior = form_cols[2].selectbox(
                    "Expense behavior",
                    [value.value for value in ExpenseBehavior],
                    index=[value.value for value in ExpenseBehavior].index(
                        item.effective_classification.expense_behavior.value
                    ),
                    key=f"behavior-{item.transaction_id}",
                )
                if st.button("Save transaction override", key=f"override-{item.transaction_id}"):
                    classifier.save_override(
                        item.transaction_id,
                        economic_class=selected_class,
                        analysis_category=selected_category or None,
                        expense_behavior=selected_behavior,
                        reason="Saved from classification review",
                    )
                    st.success("Override saved.")
                    st.rerun()
                if st.button("Clear transaction override", key=f"clear-{item.transaction_id}"):
                    classifier.clear_override(item.transaction_id)
                    st.success("Override tombstone appended.")
                    st.rerun()

        with st.expander("Preview an exact reusable rule"):
            rule_cols = st.columns(4)
            rule_account = rule_cols[0].text_input("Account", value="bank", key="rule-account")
            rule_direction = rule_cols[1].selectbox(
                "Direction", ["debit", "credit", "zero"], key="rule-direction"
            )
            rule_currency = rule_cols[2].text_input("Currency", value="ILS", key="rule-currency")
            rule_class = rule_cols[3].selectbox(
                "Class", [value.value for value in EconomicClass], key="rule-class"
            )
            rule_cols = st.columns(4)
            rule_category = rule_cols[0].text_input("Source category", key="rule-category")
            rule_movement = rule_cols[1].text_input("Movement type", key="rule-movement")
            rule_analysis_category = rule_cols[2].text_input(
                "Analysis category", key="rule-analysis-category"
            )
            rule_behavior = rule_cols[3].selectbox(
                "Expense behavior",
                [value.value for value in ExpenseBehavior],
                index=(
                    [value.value for value in ExpenseBehavior].index("unknown")
                    if rule_class in {"consumption", "refund"}
                    else [value.value for value in ExpenseBehavior].index("not_applicable")
                ),
                key="rule-behavior",
            )
            if rule_category:
                rule_payload = {
                    "account_kind": rule_account,
                    "direction": rule_direction,
                    "source_category": rule_category,
                    "source_movement_type": rule_movement,
                    "currency": rule_currency,
                    "economic_class": rule_class,
                    "analysis_category": rule_analysis_category or None,
                    "expense_behavior": rule_behavior,
                    "reason": "Saved from classification review",
                }
                preview = classifier.preview_rule(rule_payload)
                st.write(f"Exact rule would affect {preview['count']} accepted transaction(s).")
                if st.button("Create reusable rule", key="create-rule"):
                    classifier.create_rule(rule_payload)
                    st.success("Reusable rule revision saved.")
                    st.rerun()

        existing_rules = classifier.list_rules()
        if existing_rules:
            st.subheader("Reusable rule history")
            for rule in existing_rules:
                if not rule["is_current"]:
                    status = "superseded"
                elif rule["effective_active"]:
                    status = "active"
                else:
                    status = "disabled"
                st.write(
                    f"Revision {rule['revision']} · {status} · {rule['account_kind']} / "
                    f"{rule['direction']} / {rule['source_category']} / "
                    f"{rule['source_movement_type'] or '(no movement type)'} → "
                    f"{rule['economic_class']}"
                )
                if status == "active" and st.button(
                    "Disable rule", key=f"disable-rule-{rule['id']}"
                ):
                    classifier.disable_rule(int(rule["id"]))
                    st.success("Rule tombstone saved.")
                    st.rerun()

    with metrics_tab:
        st.subheader("Validation-oriented monthly metrics")
        metric_month = st.text_input("Metrics month", value=__import__("datetime").date.today().strftime("%Y-%m"))
        metric_currency = st.text_input("Metrics currency", value="ILS")
        try:
            selected_month = __import__("datetime").date.fromisoformat(f"{metric_month}-01")
            monthly = metrics_service.calculate_monthly_metrics(selected_month, metric_currency)
            completeness_status = "Complete month" if monthly.completeness.complete else "Incomplete month"
            if monthly.completeness.source_coverage == "unknown":
                coverage_note = (
                    "Source coverage is unknown; completeness applies only to imported sources."
                )
            else:
                coverage_note = f"Source coverage: {monthly.completeness.source_coverage}."
            completeness_detail = "; ".join(monthly.completeness.issues)
            message = ". ".join(
                part for part in (completeness_status, completeness_detail, coverage_note) if part
            )
            (st.warning if not monthly.completeness.complete else st.info)(message)
            st.dataframe(
                [
                    {"metric": key, "value": value, "contributors": monthly.contributors_for(key)}
                    for key, value in {
                        "gross_income": monthly.gross_income,
                        "gross_consumption": monthly.gross_consumption,
                        "refunds": monthly.refunds,
                        "net_consumption": monthly.net_consumption,
                        "operating_surplus_or_deficit": monthly.operating_surplus_or_deficit,
                        "savings_rate": monthly.savings_rate,
                        "savings_contributions": monthly.savings_contributions,
                        "savings_withdrawals": monthly.savings_withdrawals,
                        "net_observed_savings_transfers": monthly.net_observed_savings_transfers,
                    }.items()
                ],
                use_container_width=True,
            )
            drill_metric = st.selectbox(
                "Drill down", list(monthly.breakdowns), key="metric-drilldown"
            )
            st.dataframe(
                metrics_service.get_metric_contributors(
                    selected_month, drill_metric, metric_currency
                ),
                use_container_width=True,
            )
        except ValueError as exc:
            st.warning(str(exc))
