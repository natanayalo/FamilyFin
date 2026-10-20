import { MonthPicker, isValidMonth } from "@/components/ui/month-picker";

export const isValidReportMonth = isValidMonth;

export function HebrewMonthField({ name, label, boundary, value, onChange }: {
  name: string;
  label: string;
  boundary: "התחלה" | "סיום" | "להצגה";
  value: string;
  onChange: (value: string) => void;
}) {
  return <div className="dashboard-month-field">
    <label htmlFor={`report-${name}`}>{label}</label>
    <MonthPicker id={`report-${name}`} name={name} label={`חודש ${boundary}`} value={value} onChange={onChange} />
  </div>;
}
