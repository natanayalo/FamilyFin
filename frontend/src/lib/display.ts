/** Format service decimals without converting money to floating point. */
export function currencyLabel(currency: string) {
  return ({ ILS: "ש״ח", USD: "$", EUR: "€", GBP: "£" } as Record<string, string>)[currency] ?? currency;
}

export function formatAmount(amount: string | null | undefined, currency = "ILS") {
  if (amount == null) return "לא זמין";
  if (amount === "") return "לא הוזן";
  const [whole, fraction] = amount.split(".");
  const number = `${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}${fraction !== undefined ? `.${fraction}` : ""}`;
  // Hebrew money reads number, then currency from the right. Isolate the numeric
  // run as LTR so its sign and decimals cannot be reordered by nearby Hebrew,
  // even inside a caller's <bdi dir="auto"> or an LTR table cell.
  return `\u2067\u2066${number}\u2069 ${currencyLabel(currency)}\u2069`;
}

function dateFromIsoParts(value: string, pattern: RegExp) {
  const match = pattern.exec(value);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3] ?? 1);
  const date = new Date(Date.UTC(year, month - 1, day));
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return null;
  return date;
}

/** Format a service month in Hebrew while keeping its Gregorian year explicit. */
export function formatHebrewMonth(value: string) {
  const date = dateFromIsoParts(value, /^(\d{4})-(\d{2})(?:-(\d{2}))?$/);
  if (!date) return value;
  return new Intl.DateTimeFormat("he-IL", { month: "long", year: "numeric", timeZone: "UTC" }).format(date);
}

/** Format a date-only service value without introducing a time or timezone shift. */
export function formatHebrewDate(value: string) {
  const date = dateFromIsoParts(value, /^(\d{4})-(\d{2})-(\d{2})$/);
  if (!date) return value;
  return new Intl.DateTimeFormat("he-IL", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" }).format(date);
}

/** Format an actual timestamp in the user's local timezone; preserve unknown source values. */
export function formatHebrewDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat("he-IL", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

/** Use the service's day count without recalculating its freshness date. */
export function formatHebrewDaysAgo(days: number) {
  if (days === 0) return "לפני פחות מיום";
  if (days === 1) return "לפני יום";
  if (days === 2) return "לפני יומיים";
  return `לפני ${days} ימים`;
}

function shiftDecimal(value: string, places: number) {
  const text = value.trim().replace(/%$/, "").trim();
  if (!/^-?(?:\d+(?:\.\d*)?|\.\d+)$/.test(text)) return "0";
  const negative = text.startsWith("-");
  const [whole, fraction = ""] = (negative ? text.slice(1) : text).split(".");
  const digits = `${whole || "0"}${fraction}`;
  const position = (whole || "0").length + places;
  const shifted = position <= 0 ? `0.${"0".repeat(-position)}${digits}`
    : position >= digits.length ? `${digits}${"0".repeat(position - digits.length)}`
    : `${digits.slice(0, position)}.${digits.slice(position)}`;
  const normalized = shifted.replace(/^0+(?=\d)/, "").replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
  return `${negative && normalized !== "0" ? "-" : ""}${normalized}`;
}

export const rateToPercent = (rate: string) => shiftDecimal(rate, 2);
export const percentToRate = (percent: string) => shiftDecimal(percent, -2);
export const formatPercent = (rate: string | null | undefined) => rate == null ? "לא זמין" : `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(Number(rateToPercent(rate)))}%`;

export function issueLabel(code: string) {
  const labels: Record<string, string> = {
    ALLOCATION_DATE_DIFFERS: "חודש השיוך שונה מחודש העסקה - בדקו לאיזה חודש היא שייכת",
    MISSING_MOVEMENT_TYPE: "סוג התנועה חסר - בדקו אם זו הכנסה, הוצאה או העברה",
    MISSING_ORIGINAL_VALUE: "סכום המקור חסר - בדקו את העסקה מול פירוט הבנק או הכרטיס",
    NON_ILS_CURRENCY: "העסקה במטבע זר - בדקו את המטבע ואת הסכום המדווח",
    ZERO_AMOUNT_WITH_ORIGINAL_VALUE: "הסכום המדווח הוא אפס למרות שקיים סכום במקור - בדקו אם נדרש תיקון",
    SOURCE_PERIOD_PARTIAL_OR_UNKNOWN: "כיסוי תקופת המקור חלקי או לא ידוע",
    SOURCE_PERIOD_INCOMPLETE: "תקופת המקור אינה מלאה",
    RECONCILIATION_REQUIRED: "נמצאו עסקאות דומות - נדרשת החלטת התאמה",
    OPEN_RECONCILIATION_CASES: "קיימות התאמות פתוחות",
    UNCLASSIFIED_TRANSACTION: "לא נמצא סיווג מתאים לעסקה",
    INVALID_CLASS_SIGN: "הסיווג אינו תואם לכיוון העסקה",
    STALE_AMOUNT_CORRECTION: "סכומי המקור השתנו מאז התיקון ויש לאמת אותו מחדש",
    DESCRIPTION_TRANSFER_SIGNAL: "ייתכן שזו העברה; יש לבדוק את היעד",
    UNCLASSIFIED_TRANSACTIONS: "קיימות עסקאות ללא סיווג",
  };
  return labels[code] ?? "נדרשת בדיקת נתונים";
}

export function importStatusLabel(status: string) {
  return ({ committed: "הושלם", completed: "הושלם", previewed: "תצוגה מקדימה", failed: "נכשל", pending: "ממתין" } as Record<string, string>)[status] ?? "דורש בדיקה";
}

export function originLabel(origin: string) {
  return ({ manual: "הוזן ידנית", historical: "מהיסטוריית העסקאות", history: "מהיסטוריית העסקאות", csv: "מקובץ תכנון" } as Record<string, string>)[origin] ?? "מקור מיובא";
}

/** Translate system explanations; preserve custom rule and household notes. */
export function classificationExplanation(text: string) {
  const labels: Record<string, string> = {
    "Ordinary negative bank or card purchase.": "רכישה בחשבון בנק או בכרטיס אשראי שסווגה כהוצאה.",
    "The zero reporting amount was reviewed and has no financial effect.": "הסכום הוא אפס. השורה נבדקה ואינה משפיעה על ההכנסות או ההוצאות.",
    "Matched the latest active reusable rule.": "העסקה התאימה לכלל הסיווג הפעיל האחרון.",
    "A transaction-specific override is the effective decision.": "הסיווג נקבע לפי תיקון ידני לעסקה זו.",
    "Zero amount or original-amount anomaly requires review.": "סכום אפס או חריגה בסכום המקור מחייבים בדיקה.",
    "Cash withdrawals have no reliable economic destination in the source.": "מקור הנתונים אינו מפרט למה שימש המזומן שנמשך.",
    "Loan interest is treated as consumption; behavior remains unknown.": "ריבית ההלוואה סווגה כהוצאה; לא ידוע אם היא קבועה או משתנה.",
    "The source explicitly identifies the debt-principal component.": "מקור הנתונים מזהה במפורש החזר של קרן החוב.",
    "An unsplit loan payment does not reveal interest versus principal.": "תשלום ההלוואה אינו מפריד בין ריבית להחזר קרן.",
    "A bank row explicitly labeled as a variable credit-card charge is a settlement.": "חיוב כרטיס האשראי בחשבון הבנק סווג כסילוק הכרטיס.",
    "Positive bank salary or business-income category.": "זיכוי בחשבון בנק שסומן במקור כמשכורת או הכנסה מעסק.",
    "Positive refund-category row reduces consumption in its booking month.": "ההחזר מקטין את ההוצאות בחודש שבו נרשם.",
    "The source category explicitly identifies savings or investment activity.": "קטגוריית המקור מזהה במפורש פעילות חיסכון או השקעה.",
    "Positive card income-like rows are not assumed to be household income.": "זיכוי בכרטיס אינו מסווג אוטומטית כהכנסה משפחתית.",
    "An unlinked transfer cannot be assigned to an internal or external account.": "לא ידוע אם ההעברה היא בין חשבונות המשפחה או לחשבון חיצוני.",
    "Generic positive or otherwise ambiguous source row remains unclassified.": "פרטי המקור אינם מספיקים כדי לסווג את העסקה.",
    "A description-only transfer signal requires review because the source labels do not identify the economic destination.": "תיאור העסקה מרמז על העברה, אך פרטי המקור אינם מזהים את היעד. נדרשת בדיקה.",
    "The effective class conflicts with the transaction direction and was marked unclassified.": "הסיווג אינו תואם לכיוון העסקה, ולכן היא סומנה כלא מסווגת.",
    "The imported amounts changed after the correction and require review.": "סכומי המקור השתנו מאז התיקון ויש לאמת את הסכום והסיווג מחדש.",
  };
  return labels[text] ?? text;
}
