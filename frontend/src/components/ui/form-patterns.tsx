import { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";

export function FormField({ id, label, hint, error, required, children }: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  required?: boolean;
  children: ReactNode;
}) {
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  return <div className="form-field"><label className="form-label" htmlFor={id}>{label}{required && <span aria-hidden="true"> *</span>}</label>{children}{hint && <div className="field-hint" id={hintId}>{hint}</div>}{error && <div className="field-error" id={errorId} role="alert">{error}</div>}</div>;
}

export function TextField({ id, label, hint, error, required, ...inputProps }: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  required?: boolean;
} & Omit<InputHTMLAttributes<HTMLInputElement>, "id">) {
  const describedBy = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(" ") || undefined;
  return <FormField id={id} label={label} hint={hint} error={error} required={required}><input className="control-input" id={id} required={required} aria-invalid={Boolean(error)} aria-describedby={describedBy} {...inputProps} /></FormField>;
}

export function SelectField({ id, label, hint, error, required, children, ...selectProps }: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  required?: boolean;
  children: ReactNode;
} & Omit<SelectHTMLAttributes<HTMLSelectElement>, "id">) {
  const describedBy = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(" ") || undefined;
  return <FormField id={id} label={label} hint={hint} error={error} required={required}><select className="control-input" id={id} required={required} aria-invalid={Boolean(error)} aria-describedby={describedBy} {...selectProps}>{children}</select></FormField>;
}

export function FormErrorSummary({ errors, title = "יש לתקן את השדות הבאים" }: { errors: Array<{ fieldId: string; fieldLabel: string; message: string }>; title?: string }) {
  if (!errors.length) return null;
  return <div className="form-error-summary" role="alert" aria-live="assertive"><strong>{title}</strong><ul>{errors.map((error, index) => <li key={`${error.fieldId}-${index}`}><a href={`#${error.fieldId}`}>{error.fieldLabel}</a>: {error.message}</li>)}</ul></div>;
}

export function FormActions({ children }: { children: ReactNode }) {
  return <div className="form-actions">{children}</div>;
}
