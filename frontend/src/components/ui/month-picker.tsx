"use client";

import { useId, useLayoutEffect, useRef, useState, type AriaAttributes, type KeyboardEvent } from "react";
import { Popover } from "@base-ui/react/popover";
import { CalendarDays, ChevronLeft, ChevronRight, X } from "lucide-react";
import styles from "./month-picker.module.css";

export const hebrewMonths = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"];
export const isValidMonth = (value: string) => /^[0-9]{4}-(0[1-9]|1[0-2])$/.test(value) && Number(value.slice(0, 4)) > 0;
const monthIndex = (value: string) => Number(value.slice(0, 4)) * 12 + Number(value.slice(5, 7)) - 1;
const monthValue = (index: number) => `${String(Math.floor(index / 12)).padStart(4, "0")}-${String(index % 12 + 1).padStart(2, "0")}`;
const todayMonth = () => `${new Date().getFullYear()}-${String(new Date().getMonth() + 1).padStart(2, "0")}`;

type MonthPickerProps = Pick<AriaAttributes, "aria-invalid" | "aria-describedby"> & {
  id?: string;
  name?: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  min?: string;
  max?: string;
  disabled?: boolean;
  showLabel?: boolean;
  allowClear?: boolean;
  placeholder?: string;
  clearLabel?: string;
};

/** A Gregorian month value with Hebrew presentation, shared by reports and forms. */
export function MonthPicker({ id, name, label, value, onChange, min, max, disabled = false, showLabel = false, allowClear = false, placeholder = "בחירת חודש", clearLabel = "ניקוי הבחירה", ...aria }: MonthPickerProps) {
  const generatedId = useId();
  const triggerId = id ?? generatedId;
  const valid = isValidMonth(value);
  const lower = min && isValidMonth(min) ? monthIndex(min) : 12;
  const upper = max && isValidMonth(max) ? monthIndex(max) : 9999 * 12 + 11;
  const initial = Math.max(lower, Math.min(upper, monthIndex(valid ? value : todayMonth())));
  const [open, setOpen] = useState(false);
  const [year, setYear] = useState(Math.floor(initial / 12));
  const [focusedMonth, setFocusedMonth] = useState(initial % 12);
  const monthButtons = useRef<Array<HTMLButtonElement | null>>([]);
  const moveFocus = useRef(false);
  const selectedIndex = valid ? monthIndex(value) : null;
  const available = (index: number) => index >= lower && index <= upper;
  const text = valid ? `${hebrewMonths[Number(value.slice(5, 7)) - 1]} ${Number(value.slice(0, 4))}` : placeholder;

  useLayoutEffect(() => {
    if (moveFocus.current) {
      monthButtons.current[focusedMonth]?.focus();
      moveFocus.current = false;
    }
  }, [year, focusedMonth]);

  function select(index: number) {
    if (!available(index) || disabled) return;
    setOpen(false);
    onChange(monthValue(index));
  }
  function browseYear(nextYear: number) {
    const index = Math.max(lower, Math.min(upper, nextYear * 12 + focusedMonth));
    setYear(Math.floor(index / 12));
    setFocusedMonth(index % 12);
  }
  function navigate(event: KeyboardEvent<HTMLButtonElement>, month: number) {
    const offset = { ArrowLeft: 1, ArrowRight: -1, ArrowDown: 3, ArrowUp: -3, Home: -(month % 3), End: 2 - month % 3 }[event.key];
    if (offset === undefined) return;
    event.preventDefault();
    const index = Math.max(lower, Math.min(upper, year * 12 + month + offset));
    moveFocus.current = true;
    if (index === year * 12 + focusedMonth) { monthButtons.current[index % 12]?.focus(); moveFocus.current = false; }
    setYear(Math.floor(index / 12));
    setFocusedMonth(index % 12);
  }

  return <div className={styles.field}>
    {showLabel && <label htmlFor={triggerId}>{label}</label>}
    <Popover.Root open={open && !disabled} onOpenChange={(next) => {
      if (next) { setYear(Math.floor(initial / 12)); setFocusedMonth(initial % 12); }
      setOpen(next);
    }}>
      <div className={styles.control} role="group" aria-label={`בחירת ${label}`} dir="rtl">
        <button type="button" className={styles.arrow} aria-label={`${label}: החודש הקודם`} disabled={disabled || selectedIndex === null || !available(selectedIndex - 1)} onClick={() => select(selectedIndex! - 1)}><ChevronRight size={18} /></button>
        <Popover.Trigger id={triggerId} className={styles.trigger} disabled={disabled} aria-label={label} aria-invalid={aria["aria-invalid"]} aria-describedby={[`${triggerId}-value`, aria["aria-describedby"]].filter(Boolean).join(" ")}>
          <span id={`${triggerId}-value`}>{text}</span><CalendarDays size={16} aria-hidden="true" />
        </Popover.Trigger>
        <button type="button" className={styles.arrow} aria-label={`${label}: החודש הבא`} disabled={disabled || selectedIndex === null || !available(selectedIndex + 1)} onClick={() => select(selectedIndex! + 1)}><ChevronLeft size={18} /></button>
      </div>
      <Popover.Portal>
        <Popover.Positioner sideOffset={8} collisionPadding={12} className={styles.positioner}>
          <Popover.Popup className={styles.popup} dir="rtl" initialFocus={() => monthButtons.current[focusedMonth]}>
            <div className={styles.heading}><Popover.Title>{label}</Popover.Title><Popover.Close className={styles.icon} aria-label="סגירת לוח החודשים"><X size={16} /></Popover.Close></div>
            <div className={styles.year}>
              <button type="button" className={styles.icon} aria-label="השנה הקודמת" disabled={year <= Math.floor(lower / 12)} onClick={() => browseYear(year - 1)}><ChevronRight size={18} /></button>
              <strong aria-live="polite">{year}</strong>
              <button type="button" className={styles.icon} aria-label="השנה הבאה" disabled={year >= Math.floor(upper / 12)} onClick={() => browseYear(year + 1)}><ChevronLeft size={18} /></button>
            </div>
            <div className={styles.months} role="group" aria-label="חודשי השנה">
              {hebrewMonths.map((month, index) => <button type="button" key={month} ref={(node) => { monthButtons.current[index] = node; }} disabled={!available(year * 12 + index)} tabIndex={index === focusedMonth ? 0 : -1} aria-label={`${month} ${year}`} aria-pressed={selectedIndex === year * 12 + index} onFocus={() => setFocusedMonth(index)} onKeyDown={(event) => navigate(event, index)} onClick={() => select(year * 12 + index)}>{month}</button>)}
            </div>
            <div className={styles.footer}>
              <button type="button" disabled={!available(monthIndex(todayMonth()))} onClick={() => select(monthIndex(todayMonth()))}>החודש הנוכחי</button>
              {allowClear && <button type="button" onClick={() => { setOpen(false); onChange(""); }}>{clearLabel}</button>}
            </div>
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
    {name && <input type="hidden" name={name} value={value} disabled={disabled} />}
  </div>;
}
