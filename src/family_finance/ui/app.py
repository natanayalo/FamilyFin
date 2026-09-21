"""Local Streamlit dashboard with shared filters and domain-service data."""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal

os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")


def main() -> None:
    import streamlit as st
    from sqlalchemy.exc import SQLAlchemyError

    from family_finance.dashboard import DashboardService
    from family_finance.formatting import format_amount, format_month, format_rate
    from family_finance.models import (
        DashboardFilters,
        EconomicClass,
        ExpenseBehavior,
        PlanningFrequency,
        PlanningItem,
        PlanningItemInput,
        PlanningItemKind,
    )
    from family_finance.planning import (
        DuplicateSeedError,
        PlanningPreviewStaleError,
        PlanningValidationError,
        StaleRevisionError,
    )
    from family_finance.services import ImportService, PreviewStaleError

    st.set_page_config(page_title="Family Finance", page_icon="💰", layout="wide")
    service = ImportService()
    dashboard = DashboardService(
        service.database,
        metrics=service.metrics_service,
        classifier=service.classification_service,
    )
    classifier = service.classification_service

    default_filters = dashboard.default_filters()
    currencies = sorted({
        str(row["currency"]).upper() for row in dashboard.repository.accepted_transactions()
    } | {"ILS"})
    sidebar = st.sidebar
    sidebar.title("Family Finance")
    saved_currency = st.session_state.get("dashboard_currency", default_filters.currency)
    if saved_currency not in currencies:
        saved_currency = default_filters.currency
    currency = sidebar.selectbox(
        "Currency scope", currencies,
        index=currencies.index(saved_currency),
    )
    start_default = st.session_state.get("dashboard_start", default_filters.start_month)
    end_default = st.session_state.get("dashboard_end", default_filters.end_month)
    start_month = sidebar.date_input("Start month", value=start_default, key="dashboard_start_input")
    end_month = sidebar.date_input("End month", value=end_default, key="dashboard_end_input")
    start_month = start_month.replace(day=1)
    end_month = end_month.replace(day=1)
    try:
        filters = DashboardFilters(start_month=start_month, end_month=end_month, currency=currency)
    except ValueError as exc:
        sidebar.error(str(exc))
        filters = default_filters
    st.session_state["dashboard_currency"] = filters.currency
    st.session_state["dashboard_start"] = filters.start_month
    st.session_state["dashboard_end"] = filters.end_month
    sidebar.caption("Local-only · ILS and other currencies are never combined")

    def render_banner(point) -> None:
        if point is None:
            st.info("No accepted transactions are available for this scope.")
            return
        metrics = point.metrics
        if point.complete:
            st.success(f"{format_month(point.month)} is complete for {point.currency}.")
        else:
            st.warning(
                f"{format_month(point.month)} is provisional: "
                + ", ".join(point.issue_codes or ["completeness policy"]) + "."
            )
        st.caption(
            f"Freshness: {metrics.data_freshness_date or 'unavailable'} · "
            f"Source coverage: {metrics.completeness.source_coverage} · "
            f"Currency: {point.currency}"
        )

    def overview_page() -> None:
        st.title("Overview")
        result = dashboard.overview(filters)
        selected = result.selected_month
        render_banner(selected)
        if selected is None:
            return
        values = result.headline
        cols = st.columns(5)
        cols[0].metric("Income", format_amount(values["income"], result.currency))
        cols[1].metric("Net consumption", format_amount(values["net_consumption"], result.currency))
        cols[2].metric("Operating surplus / deficit", format_amount(values["operating_surplus_or_deficit"], result.currency))
        cols[3].metric("Savings rate", format_rate(values["savings_rate"]))
        cols[4].metric("Observed savings transfers", format_amount(values["net_observed_savings_transfers"], result.currency))
        st.caption("Operating surplus and observed savings transfers are separate measures.")

        import pandas as pd
        import plotly.express as px

        rows = [
            {
                "month": item.month,
                "income": item.metrics.gross_income,
                "consumption": item.metrics.net_consumption,
                "operating_surplus": item.metrics.operating_surplus_or_deficit,
                "status": "complete" if item.complete else "provisional",
            }
            for item in result.series
        ]
        frame = pd.DataFrame(rows)
        st.plotly_chart(
            px.line(frame, x="month", y=["income", "consumption"], markers=True, title="Income versus consumption"),
            use_container_width=True,
        )
        st.plotly_chart(
            px.line(frame, x="month", y="operating_surplus", color="status", markers=True, title="Operating surplus / deficit"),
            use_container_width=True,
        )
        st.subheader("Comparisons and averages")
        comparison_rows = [item.model_dump(mode="json") for item in result.comparisons]
        st.dataframe(comparison_rows, use_container_width=True, hide_index=True)
        st.dataframe(
            [
                {
                    "month": item.month,
                    "complete": item.complete,
                    "income": item.metrics.gross_income,
                    "net_consumption": item.metrics.net_consumption,
                    "three_month_average": item.metrics.rolling_three_month_averages.get("net_consumption"),
                    "six_month_average": item.metrics.rolling_six_month_averages.get("net_consumption"),
                }
                for item in result.series
            ],
            use_container_width=True,
            hide_index=True,
        )

    def expenses_page() -> None:
        st.title("Expenses")
        result = dashboard.expenses(filters)
        selected = result.selected_month
        render_banner(selected)
        if selected is None:
            return
        st.subheader("End-month category distribution")
        st.dataframe(
            [item.model_dump(mode="json") for item in result.categories],
            use_container_width=True,
            hide_index=True,
        )
        st.subheader("Fixed, variable, and unknown behavior")
        st.bar_chart(result.behavior_totals)
        st.subheader("Monthly category trends")
        category_names = sorted({category for item in result.series for category in item.metrics.spending_by_category})
        if category_names:
            import pandas as pd
            trend = pd.DataFrame(
                {
                    "month": item.month,
                    **{category: item.metrics.spending_by_category.get(category, 0) for category in category_names},
                }
                for item in result.series
            ).set_index("month")
            st.line_chart(trend)
        st.subheader("Exact transaction drill-down")
        month_options = [item.month for item in result.series]
        selected_month = st.selectbox("Month", month_options, format_func=format_month)
        month_metrics = next(item.metrics for item in result.series if item.month == selected_month)
        selected_category = st.selectbox("Category", ["(all categories)"] + category_names)
        metric_options = sorted(
            metric
            for metric in month_metrics.breakdowns
            if selected_category == "(all categories)"
            or metric == f"spending_by_category:{selected_category}"
            or not metric.startswith("spending_by_category:")
        )
        metric = st.selectbox("Metric", metric_options, format_func=lambda item: item.replace("_", " "))
        contributor_ids = month_metrics.contributors_for(metric)
        st.caption(f"{len(contributor_ids)} contributing transaction(s)")
        st.dataframe(
            [item.model_dump(mode="json") for item in dashboard.contributors(contributor_ids)],
            use_container_width=True,
            hide_index=True,
        )
        st.subheader("End-month category MoM and YoY")
        st.dataframe(
            [item.model_dump(mode="json") for item in result.category_comparisons],
            use_container_width=True,
            hide_index=True,
        )
        st.subheader("Deterministic insights")
        st.caption("These are potential patterns, not accounting classifications.")
        if result.potential_recurring_spending:
            st.write("Potential recurring spending")
            st.dataframe(
                [item.model_dump(mode="json") for item in result.potential_recurring_spending],
                use_container_width=True,
                hide_index=True,
            )
            recurring_index = st.selectbox(
                "Recurring pattern transactions",
                range(len(result.potential_recurring_spending)),
                format_func=lambda index: (
                    f"{result.potential_recurring_spending[index].normalized_description} · "
                    f"{result.potential_recurring_spending[index].analysis_category}"
                ),
                key="recurring-insight-drilldown",
            )
            recurring = result.potential_recurring_spending[recurring_index]
            st.dataframe(
                [item.model_dump(mode="json") for item in dashboard.contributors(
                    recurring.contributor_transaction_ids
                )],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No qualifying recurring-spending patterns in this range.")
        if result.unusual_category_spending:
            st.write("Unusual category spending")
            st.dataframe(
                [item.model_dump(mode="json") for item in result.unusual_category_spending],
                use_container_width=True,
                hide_index=True,
            )
            anomaly_index = st.selectbox(
                "Anomaly transactions",
                range(len(result.unusual_category_spending)),
                format_func=lambda index: (
                    f"{format_month(result.unusual_category_spending[index].month)} · "
                    f"{result.unusual_category_spending[index].category} · "
                    f"{result.unusual_category_spending[index].direction}"
                ),
                key="anomaly-insight-drilldown",
            )
            anomaly = result.unusual_category_spending[anomaly_index]
            st.dataframe(
                [item.model_dump(mode="json") for item in dashboard.contributors(
                    anomaly.contributor_transaction_ids
                )],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No qualifying category anomalies in this range.")

    def data_quality_page() -> None:
        st.title("Data Quality")
        quality = dashboard.data_quality(filters)
        cols = st.columns(6)
        cols[0].metric("Accepted rows", sum(quality.currencies.values()))
        cols[1].metric("Freshness", quality.freshness_date or "Unavailable")
        cols[2].metric("Open reconciliation", quality.open_reconciliation_cases)
        cols[3].metric("Unclassified", quality.unclassified_transaction_count)
        cols[4].metric("Incomplete months", len(quality.incomplete_months))
        cols[5].metric("Currencies", ", ".join(quality.currencies) or "Unavailable")
        st.write({
            "covered_period": [quality.covered_start, quality.covered_end],
            "issue_counts": quality.issue_counts,
            "unclassified_absolute_amount": format_amount(quality.unclassified_absolute_amount, filters.currency),
        })
        st.write("Latest import", quality.latest_import or "No imports committed.")
        if quality.unclassified_transaction_count:
            st.warning("Review items prevent complete metrics. Open the Classification page to resolve them.")
        st.subheader("Upload and import")
        upload = st.file_uploader("Upload a FamilyBiz XLSX export", type=["xlsx"])
        if upload is not None and st.button("Inspect and preview", type="primary"):
            try:
                preview = service.preview_import(upload.getvalue(), upload.name)
                st.session_state["family_finance_preview"] = preview.model_dump(mode="json")
                st.session_state["family_finance_file"] = upload.getvalue()
                st.session_state["family_finance_filename"] = upload.name
            except (ValueError, OSError, SQLAlchemyError) as exc:
                st.error(str(exc))
        preview = st.session_state.get("family_finance_preview")
        if preview:
            st.json({"inspection": preview["inspection"], "issue_counts": preview["issue_counts"], "sample": preview["preview_rows"][:10]})
            if st.button("Commit import"):
                try:
                    result = service.commit_import(
                        st.session_state["family_finance_file"], preview["preview_token"], st.session_state.get("family_finance_filename")
                    )
                    st.success(f"{result.status.value}: {result.statistics.model_dump(mode='json')}")
                    st.session_state.pop("family_finance_preview", None)
                    st.rerun()
                except (PreviewStaleError, ValueError, OSError, SQLAlchemyError) as exc:
                    st.error(str(exc))
        st.subheader("Import history")
        st.dataframe(service.history(), use_container_width=True, hide_index=True)
        st.subheader("Open reconciliation cases")
        cases = service.reconciliation_cases()
        if not cases:
            st.info("No open reconciliation cases.")
        for case in cases:
            with st.expander(f"Case {case['id']}"):
                st.json({"incoming": case["source"], "candidates": case["candidates"]})
                choices = ["Accept as new", "Dismiss"] + [f"Link to transaction {candidate['id']}" for candidate in case["candidates"]]
                choice = st.selectbox("Resolution", choices, key=f"resolution-{case['id']}")
                if st.button("Apply resolution", key=f"apply-{case['id']}"):
                    decision = {"resolution": "accept_as_new" if choice == "Accept as new" else "dismiss"}
                    if choice.startswith("Link to transaction"):
                        decision = {"resolution": "link_existing", "transaction_id": int(choice.split()[-1])}
                    service.resolve_reconciliation(case["id"], decision)
                    st.rerun()

    def classification_page() -> None:
        st.title("Classification")
        st.caption("Append-only review decisions and reusable exact-match rules")
        filter_cols = st.columns(6)
        review_month = filter_cols[0].text_input("Month", placeholder="YYYY-MM", key="review-month")
        review_account = filter_cols[1].text_input("Account kind", key="review-account")
        review_currency = filter_cols[2].text_input("Currency", value=filters.currency, key="review-currency")
        review_issue = filter_cols[3].text_input("Issue code", key="review-issue")
        review_class = filter_cols[4].selectbox("Economic class", ["(all)"] + [value.value for value in EconomicClass], key="review-class")
        review_source = filter_cols[5].selectbox("Classification source", ["(all)", "override", "reusable_rule", "builtin_rule", "unclassified"], key="review-source")
        show_resolved = st.checkbox("Show classified rows", value=False)
        month_value = None
        if review_month:
            try:
                month_value = date.fromisoformat(f"{review_month}-01")
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
            with st.expander(f"Transaction {item.transaction_id} · {item.booking_date} · {item.amount} {item.currency}"):
                st.json({"source_fields": item.source_fields, "effective_classification": item.effective_classification.model_dump(mode="json"), "issues": [issue.model_dump(mode="json") for issue in item.issues]})
                form_cols = st.columns(3)
                selected_class = form_cols[0].selectbox("Economic class", [value.value for value in EconomicClass], index=[value.value for value in EconomicClass].index(item.effective_classification.economic_class.value), key=f"class-{item.transaction_id}")
                selected_category = form_cols[1].text_input("Analysis category", value=item.effective_classification.analysis_category or "", key=f"category-{item.transaction_id}")
                selected_behavior = form_cols[2].selectbox("Expense behavior", [value.value for value in ExpenseBehavior], index=[value.value for value in ExpenseBehavior].index(item.effective_classification.expense_behavior.value), key=f"behavior-{item.transaction_id}")
                if st.button("Save transaction override", key=f"override-{item.transaction_id}"):
                    classifier.save_override(item.transaction_id, economic_class=selected_class, analysis_category=selected_category or None, expense_behavior=selected_behavior, reason="Saved from classification review")
                    st.rerun()
                if st.button("Clear transaction override", key=f"clear-{item.transaction_id}"):
                    classifier.clear_override(item.transaction_id)
                    st.rerun()
        with st.expander("Reusable-rule editor"):
            cols = st.columns(4)
            account = cols[0].text_input("Account", value="bank", key="rule-account")
            direction = cols[1].selectbox("Direction", ["debit", "credit", "zero"], key="rule-direction")
            rule_currency = cols[2].text_input("Currency", value=filters.currency, key="rule-currency")
            rule_class = cols[3].selectbox("Class", [value.value for value in EconomicClass], key="rule-class")
            cols = st.columns(4)
            category = cols[0].text_input("Source category", key="rule-category")
            movement = cols[1].text_input("Movement type", key="rule-movement")
            analysis_category = cols[2].text_input("Analysis category", key="rule-analysis-category")
            behavior = cols[3].selectbox("Expense behavior", [value.value for value in ExpenseBehavior], key="rule-behavior")
            if category:
                payload = {"account_kind": account, "direction": direction, "source_category": category, "source_movement_type": movement, "currency": rule_currency, "economic_class": rule_class, "analysis_category": analysis_category or None, "expense_behavior": behavior, "reason": "Saved from classification review"}
                preview = classifier.preview_rule(payload)
                st.caption(f"Exact rule would affect {preview['count']} accepted transaction(s).")
                if st.button("Create reusable rule"):
                    classifier.create_rule(payload)
                    st.rerun()
        st.subheader("Rule history")
        rules = classifier.list_rules()
        st.dataframe(rules, use_container_width=True, hide_index=True)
        for rule in rules:
            if rule["is_current"] and rule["effective_active"] and st.button(
                f"Disable rule revision {rule['id']}",
                key=f"disable-rule-{rule['id']}",
            ):
                classifier.disable_rule(int(rule["id"]))
                st.rerun()

    def planning_page() -> None:
        st.title("Planning")
        st.caption("Local-only 12-month scenarios. Planning assumptions never alter imported transactions.")
        planning = service.planning_service
        scenarios = planning.list_scenarios(include_archived=True)
        st.subheader("Scenarios")
        if scenarios:
            st.dataframe(
                [item.model_dump(mode="json") for item in scenarios],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No planning scenarios yet.")

        with st.expander("Create a manual scenario", expanded=not scenarios):
            cols = st.columns(4)
            manual_name = cols[0].text_input("Scenario name", value="Household baseline", key="planning-manual-name")
            manual_currency = cols[2].text_input("Currency", value="ILS", key="planning-manual-currency")
            manual_start = cols[1].date_input(
                "Start month",
                value=planning.suggested_start_month(manual_currency),
                key="planning-manual-start",
            )
            manual_kind = cols[3].selectbox("Item kind", [item.value for item in PlanningItemKind], key="planning-manual-kind")
            cols = st.columns(4)
            manual_label = cols[0].text_input("Item label", value="Monthly assumption", key="planning-manual-label")
            manual_category = cols[1].text_input("Category", key="planning-manual-category")
            manual_amount = cols[2].text_input("Amount", value="0", key="planning-manual-amount")
            manual_frequency = cols[3].selectbox("Frequency", [item.value for item in PlanningFrequency], key="planning-manual-frequency")
            if st.button("Create scenario", key="planning-create-manual"):
                try:
                    amount = Decimal(manual_amount)
                    if manual_frequency == PlanningFrequency.MONTHLY.value:
                        manual_end = manual_start.replace(day=1)
                        for _ in range(11):
                            manual_end = (
                                date(manual_end.year + 1, 1, 1)
                                if manual_end.month == 12
                                else date(manual_end.year, manual_end.month + 1, 1)
                            )
                        item = PlanningItemInput(
                            kind=manual_kind,
                            label=manual_label,
                            category=manual_category or None,
                            amount=amount,
                            frequency=manual_frequency,
                            start_month=manual_start.replace(day=1),
                            end_month=manual_end,
                        )
                    else:
                        item = PlanningItemInput(
                            kind=manual_kind,
                            label=manual_label,
                            category=manual_category or None,
                            amount=amount,
                            frequency=manual_frequency,
                            occurrence_month=manual_start.replace(day=1),
                        )
                    planning.create_manual_scenario(manual_name, manual_start, [item], currency=manual_currency)
                    st.success("Scenario created")
                    st.rerun()
                except (ValueError, PlanningValidationError) as exc:
                    st.error(str(exc))

        with st.expander("Seed from imported history"):
            history_cols = st.columns(4)
            history_name = history_cols[0].text_input("Scenario name", value="Historical baseline", key="planning-history-name")
            history_currency = history_cols[1].text_input("Currency", value="ILS", key="planning-history-currency")
            history_start = history_cols[2].date_input(
                "Scenario start month",
                value=planning.suggested_start_month(history_currency),
                key="planning-history-start",
            )
            history_months = history_cols[3].number_input("History months", min_value=1, max_value=120, value=6, step=1, key="planning-history-months")
            if st.button("Preview historical seed", key="planning-history-preview"):
                try:
                    preview = planning.preview_history_seed(
                        name=history_name,
                        currency=history_currency,
                        start_month=history_start,
                        history_months=int(history_months),
                    )
                    st.session_state["planning_history_preview"] = preview.model_dump(mode="json")
                except (ValueError, PlanningValidationError) as exc:
                    st.error(str(exc))
            history_preview = st.session_state.get("planning_history_preview")
            if history_preview:
                st.json({
                    "provisional": history_preview["provisional"],
                    "issue_codes": history_preview["issue_codes"],
                    "completeness_snapshot": history_preview["completeness_snapshot"],
                    "items": history_preview["items"],
                })
                if st.button("Commit historical seed", key="planning-history-commit"):
                    try:
                        planning.commit_history_seed(history_preview["preview_token"])
                        st.session_state.pop("planning_history_preview", None)
                        st.success("Historical scenario created")
                        st.rerun()
                    except (PlanningPreviewStaleError, PlanningValidationError) as exc:
                        st.error(str(exc))

        with st.expander("Seed from the supplied planning CSV"):
            upload = st.file_uploader("Planning CSV", type=["csv"], key="planning-csv-upload")
            csv_start = st.date_input(
                "Scenario start month",
                value=planning.suggested_start_month("ILS"),
                key="planning-csv-start",
            )
            if upload is not None and st.button("Preview CSV seed", key="planning-csv-preview"):
                try:
                    preview = planning.preview_csv_seed(upload.getvalue(), upload.name, start_month=csv_start)
                    st.session_state["planning_csv_preview"] = preview.model_dump(mode="json")
                    st.session_state["planning_csv_bytes"] = upload.getvalue()
                except (ValueError, OSError) as exc:
                    st.error(str(exc))
            preview_data = st.session_state.get("planning_csv_preview")
            if preview_data:
                st.json({
                    "control_checks": preview_data["control_checks"],
                    "ignored_sections": preview_data["ignored_sections"],
                    "warnings": preview_data["warnings"],
                    "expense_notes": preview_data.get("expense_notes", []),
                })
                st.caption("Confirm each CSV category mapping before committing. Unmapped categories remain excluded from category variance.")
                mapping_values: dict[str, str] = {}
                preview_key = preview_data.get("file_sha256") or preview_data["preview_token"][-16:]
                mapping_options = ["(unmapped)"] + planning.analysis_categories(preview_data["currency"])
                for index, mapping in enumerate(preview_data.get("mappings", [])):
                    suggestions = mapping.get("suggested_analysis_categories", [])
                    suggested = suggestions[0] if len(suggestions) == 1 else "(unmapped)"
                    default_index = mapping_options.index(suggested) if suggested in mapping_options else 0
                    selected_mapping = st.selectbox(
                        f"{mapping['csv_category']} → analysis category",
                        mapping_options,
                        index=default_index,
                        key=f"planning-csv-mapping-{preview_key}-{index}-{mapping['csv_category']}",
                    )
                    if selected_mapping != "(unmapped)":
                        mapping_values[mapping["csv_category"]] = selected_mapping
                control_gap = any(not check.get("passed", False) for check in preview_data.get("control_checks", {}).values())
                acknowledged = True
                if control_gap:
                    acknowledged = st.checkbox(
                        "I acknowledge unresolved CSV control gaps and will review the seeded assumptions.",
                        key=f"planning-csv-control-gap-ack-{preview_key}",
                    )
                if preview_data.get("duplicate_scenario_id"):
                    st.info("This file is already linked to a scenario. Duplicate that scenario explicitly to create a new plan.")
                elif st.button("Commit CSV seed", key="planning-csv-commit"):
                    try:
                        if control_gap and not acknowledged:
                            st.warning("Acknowledge the unresolved control gap before committing this seed.")
                        else:
                            planning.commit_csv_seed(
                                st.session_state["planning_csv_bytes"],
                                preview_data["preview_token"],
                                mappings=mapping_values,
                            )
                            st.session_state.pop("planning_csv_preview", None)
                            st.success("CSV scenario created")
                            st.rerun()
                    except (DuplicateSeedError, PlanningPreviewStaleError, PlanningValidationError) as exc:
                        st.error(str(exc))

        if not scenarios:
            return
        selected_id = st.selectbox(
            "Open scenario",
            [item.scenario_id for item in scenarios],
            format_func=lambda value: next(item.name for item in scenarios if item.scenario_id == value),
            key="planning-selected-scenario",
        )
        selected = planning.get_scenario(selected_id)
        revision = planning.get_revision(selected_id)
        action_cols = st.columns(4)
        if action_cols[0].button("Duplicate", key="planning-duplicate"):
            planning.clone_scenario(selected_id)
            st.rerun()
        if action_cols[1].button("Archive" if not selected.archived else "Unarchive", key="planning-archive"):
            planning.archive_scenario(selected_id, not selected.archived)
            st.rerun()
        action_cols[2].caption(f"Revision {revision.revision_number}")
        action_cols[3].caption(f"{selected.currency} · {selected.start_month} to {selected.end_month}")
        st.subheader("Revision editor")
        st.caption("Edit rows, add rows, remove rows, or change their schedule. Saving creates an immutable full revision.")
        editor_rows = [
            {
                "id": item.id,
                "kind": item.kind.value,
                "label": item.label,
                "category": item.category or "",
                "amount": str(item.amount),
                "frequency": item.frequency.value,
                "start_month": item.start_month.isoformat() if item.start_month else "",
                "end_month": item.end_month.isoformat() if item.end_month else "",
                "occurrence_month": item.occurrence_month.isoformat() if item.occurrence_month else "",
            }
            for item in revision.items
        ]
        edited_rows = st.data_editor(
            editor_rows,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            key=f"planning-editor-{selected_id}-{revision.revision_number}",
            column_config={
                "kind": st.column_config.SelectboxColumn("Kind", options=[item.value for item in PlanningItemKind], required=True),
                "frequency": st.column_config.SelectboxColumn("Frequency", options=[item.value for item in PlanningFrequency], required=True),
                "amount": st.column_config.TextColumn("Amount", required=True),
                "start_month": st.column_config.TextColumn("Start month (YYYY-MM-01)"),
                "end_month": st.column_config.TextColumn("End month (YYYY-MM-01)"),
                "occurrence_month": st.column_config.TextColumn("Occurrence month (YYYY-MM-01)"),
            },
            disabled=["id"],
        )
        revision_notes = st.text_area("Revision notes", value=revision.notes, key=f"planning-revision-notes-{selected_id}-{revision.revision_number}")

        def editor_items(rows):
            original = {item.id: item for item in revision.items}
            parsed_items = []
            for row in rows:
                values = {key: row.get(key) for key in ("id", "kind", "label", "category", "amount", "frequency", "start_month", "end_month", "occurrence_month")}
                if all(value in (None, "") for key, value in values.items() if key != "id"):
                    continue
                item_id = str(values.get("id") or "")
                kind = str(values.get("kind") or "").strip()
                frequency = str(values.get("frequency") or "").strip()
                label = str(values.get("label") or "").strip()
                amount = Decimal(str(values.get("amount") or "0"))
                schedule = {
                    "start_month": str(values.get("start_month") or "").strip() or None,
                    "end_month": str(values.get("end_month") or "").strip() or None,
                    "occurrence_month": str(values.get("occurrence_month") or "").strip() or None,
                }
                if frequency == PlanningFrequency.MONTHLY.value:
                    schedule["occurrence_month"] = None
                else:
                    schedule["start_month"] = None
                    schedule["end_month"] = None
                base = original.get(item_id)
                if base is not None:
                    payload = base.model_dump(mode="json")
                    payload.update({
                        "kind": kind,
                        "label": label,
                        "category": str(values.get("category") or "").strip() or None,
                        "amount": str(amount),
                        "frequency": frequency,
                        **schedule,
                    })
                    parsed_items.append(PlanningItem.model_validate(payload))
                else:
                    parsed_items.append(
                        PlanningItemInput(
                            kind=kind,
                            label=label,
                            category=str(values.get("category") or "").strip() or None,
                            amount=amount,
                            frequency=frequency,
                            **schedule,
                        )
                    )
            return parsed_items

        draft_items = None
        try:
            draft_items = editor_items(edited_rows)
            draft_projection = planning.project_draft(selected_id, draft_items, revision_number=revision.revision_number)
            if st.button("Save revision", key=f"planning-save-revision-{selected_id}-{revision.revision_number}"):
                planning.save_revision(selected_id, revision.revision_number, draft_items, notes=revision_notes)
                st.success("Revision saved")
                st.rerun()
        except (ValueError, PlanningValidationError) as exc:
            draft_projection = None
            st.error(f"Draft is invalid: {exc}")
        if draft_projection is not None:
            st.caption("Draft projection updates as you edit the table; save when the schedule is ready.")
            st.dataframe([month.model_dump(mode="json") for month in draft_projection.months], use_container_width=True, hide_index=True)
        st.subheader("Projection")
        projection = planning.project_draft(selected_id)
        if projection.provisional:
            st.warning("This projection is provisional: " + ", ".join(projection.issue_codes or ["seed quality gaps"]) + ".")
        st.dataframe([month.model_dump(mode="json") for month in projection.months], use_container_width=True, hide_index=True)
        st.subheader("Revision history")
        st.dataframe([item.model_dump(mode="json") for item in planning.list_revisions(selected_id)], use_container_width=True, hide_index=True)
        if revision.revision_number > 1 and st.button("Restore revision 1", key="planning-restore-first"):
            try:
                planning.restore_revision(selected_id, 1)
                st.rerun()
            except StaleRevisionError as exc:
                st.error(str(exc))
        st.subheader("Comparisons")
        compare_ids = st.multiselect(
            "Scenarios to compare (2–4)",
            [item.scenario_id for item in scenarios if item.currency == selected.currency],
            default=[selected_id] if len(scenarios) == 1 else [],
            max_selections=4,
            format_func=lambda value: next(item.name for item in scenarios if item.scenario_id == value),
            key="planning-compare-scenarios",
        )
        if len(compare_ids) >= 2:
            comparison = planning.compare_scenarios(compare_ids)
            rows = []
            for series in comparison.scenarios:
                for month, plan in zip(comparison.months, series.months):
                    rows.append({"scenario": series.name, "month": month, **(plan.model_dump(mode="json") if plan else {})})
            st.dataframe(rows, use_container_width=True, hide_index=True)
        actual = planning.compare_actual(selected_id)
        st.subheader("Actual versus plan")
        st.dataframe([item.model_dump(mode="json") for item in actual.months], use_container_width=True, hide_index=True)

    pages = [
        st.Page(overview_page, title="Overview", icon="📊"),
        st.Page(expenses_page, title="Expenses", icon="🧾"),
        st.Page(data_quality_page, title="Data Quality", icon="✅"),
        st.Page(classification_page, title="Classification", icon="🏷️"),
        st.Page(planning_page, title="Planning", icon="📅"),
    ]
    navigation = st.navigation(pages)
    navigation.run()
