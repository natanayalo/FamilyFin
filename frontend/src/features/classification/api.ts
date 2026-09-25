import { apiRequest } from "@/lib/api";
import type { ClassificationRule, Coverage, ReviewItem, RuleDraft, RulePreview } from "./types";

function query(values: Record<string, string | boolean | undefined>, cursor?: string) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== "") params.set(key, String(value));
  });
  if (cursor) params.set("cursor", cursor);
  return params.size ? `?${params.toString()}` : "";
}

export function getCoverage(filters: { month?: string; currency?: string }) {
  return apiRequest<Coverage>(`/classification/coverage${query(filters)}`);
}

export function getReviewQueue(filters: {
  month?: string;
  account_kind?: string;
  currency?: string;
  issue?: string;
  economic_class?: string;
  classification_source?: string;
  include_resolved: boolean;
}, cursor?: string) {
  return apiRequest<ReviewItem[]>(`/classification/review-queue${query(filters, cursor)}`);
}

export function getRules(cursor?: string) {
  return apiRequest<ClassificationRule[]>(`/classification/rules${query({}, cursor)}`);
}

export function saveOverride(item: ReviewItem, values: {
  economic_class: string;
  analysis_category: string | null;
  expense_behavior: string;
}) {
  return apiRequest<{ result: ReviewItem["effective_classification"]; override_version: number; expected_classification_state: string }>(
    `/classification/transactions/${item.transaction_id}/override`,
    {
      method: "POST",
      body: JSON.stringify({ expected_override_version: item.expected_override_version, expected_classification_state: item.expected_classification_state, ...values, reason: "Saved from classification review" }),
    },
  );
}

export function clearOverride(item: ReviewItem) {
  return apiRequest<{ result: ReviewItem["effective_classification"]; override_version: number; expected_classification_state: string }>(
    `/classification/transactions/${item.transaction_id}/override`,
    {
      method: "DELETE",
      body: JSON.stringify({ expected_override_version: item.expected_override_version, expected_classification_state: item.expected_classification_state }),
    },
  );
}

export function previewRule(draft: RuleDraft) {
  return apiRequest<RulePreview>("/classification/rules/previews", {
    method: "POST",
    body: JSON.stringify(draft),
  });
}

export function createRule(draft: RuleDraft, expectedCurrentRuleId: number | null) {
  return apiRequest<ClassificationRule>("/classification/rules", {
    method: "POST",
    body: JSON.stringify({ ...draft, expected_current_rule_id: expectedCurrentRuleId }),
  });
}

export function disableRule(rule: ClassificationRule) {
  return apiRequest<ClassificationRule>(`/classification/rules/${rule.id}/disable`, {
    method: "POST",
    body: JSON.stringify({ expected_current_rule_id: rule.id, reason: "Reusable rule disabled" }),
  });
}
