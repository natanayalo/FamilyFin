const currencyNames: Record<string, string> = {
  ILS: "ש״ח",
  USD: "$",
  EUR: "€",
  GBP: "£",
};

export function formatAmount(amount: string | null | undefined, currency = "ILS") {
  if (amount == null) return "לא זמין";
  const symbol = currencyNames[currency] ?? currency;
  return `${amount} ${symbol}`;
}

export function formatMonth(month: string) {
  const [year, monthNumber] = month.slice(0, 7).split("-");
  return `${monthNumber}/${year}`;
}

export function formatDate(value: string | null | undefined) {
  if (!value) return "לא זמין";
  return value.slice(0, 10).split("-").reverse().join("/");
}

export function metricLabel(metric: string) {
  const labels: Record<string, string> = {
    gross_income: "הכנסה",
    gross_consumption: "צריכה ברוטו",
    refunds: "החזרים",
    net_consumption: "צריכה נטו",
    operating_surplus_or_deficit: "עודף או גירעון תפעולי",
    savings_rate: "שיעור חיסכון",
    savings_contributions: "הפקדות לחיסכון",
    savings_withdrawals: "משיכות מחיסכון",
    net_observed_savings_transfers: "העברות חיסכון נטו",
    fixed_consumption: "הוצאות קבועות",
    variable_consumption: "הוצאות משתנות",
    unknown_behavior_consumption: "התנהגות לא ידועה",
  };
  if (metric.startsWith("spending_by_category:")) return metric.slice("spending_by_category:".length);
  return labels[metric] ?? metric;
}

export function completenessLabel(complete: boolean) {
  return complete ? "החודש מלא" : "החודש זמני";
}

export function coverageLabel(coverage: string) {
  const labels: Record<string, string> = {
    unknown: "לא ידוע",
    complete: "מלא",
    partial: "חלקי",
    estimated: "מוערך",
  };
  return labels[coverage] ?? coverage;
}

export function accountKindLabel(kind: string) {
  const labels: Record<string, string> = { bank: "חשבון בנק", card: "כרטיס אשראי", credit_card: "כרטיס אשראי" };
  return labels[kind] ?? kind;
}

export function classificationLabel(value: string) {
  const labels: Record<string, string> = {
    income: "הכנסה",
    consumption: "צריכה",
    refund: "החזר",
    internal_transfer: "העברה פנימית",
    savings_transfer: "העברת חיסכון",
    credit_card_settlement: "סילוק כרטיס אשראי",
    debt_principal: "קרן חוב",
    unclassified: "לא מסווג",
    fixed: "קבועה",
    variable: "משתנה",
    unknown: "לא ידועה",
    not_applicable: "לא חל",
    override: "תיקון ידני",
    reusable_rule: "כלל חוזר",
    builtin_rule: "כלל מערכת",
  };
  return labels[value] ?? value;
}

export function comparisonReason(reason: string | null) {
  if (!reason) return "המדיניות לא מסרה סיבה.";
  if (reason.startsWith("The selected month is provisional:")) return `החודש שנבחר זמני: ${reason.split(":").slice(1).join(":").trim()}`;
  if (reason.startsWith("The comparison month is provisional:")) return `חודש ההשוואה זמני: ${reason.split(":").slice(1).join(":").trim()}`;
  if (reason === "The comparison month is outside the selected range.") return "חודש ההשוואה מחוץ לטווח שנבחר.";
  if (reason === "The metrics policy withheld this comparison.") return "מדיניות המדדים אינה מאפשרת את ההשוואה.";
  return reason;
}

export function insightLabel(label: string) {
  return label === "Potential pattern" ? "דפוס אפשרי" : label;
}
