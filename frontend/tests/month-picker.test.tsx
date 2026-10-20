import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MonthPicker } from "@/components/ui/month-picker";

function Picker({ initial = "2026-12", min, max, onChange = () => {} }: { initial?: string; min?: string; max?: string; onChange?: (value: string) => void }) {
  const [value, setValue] = useState(initial);
  return <form><MonthPicker name="month" label="חודש לבדיקה" value={value} min={min} max={max} allowClear clearLabel="כל החודשים" placeholder="כל החודשים" onChange={(next) => { setValue(next); onChange(next); }} /></form>;
}

describe("shared Hebrew month picker", () => {
  it("steps across years and keeps the submitted month value canonical", () => {
    const { container } = render(<Picker />);
    fireEvent.click(screen.getByRole("button", { name: "חודש לבדיקה: החודש הבא" }));
    expect(screen.getByRole("button", { name: "חודש לבדיקה" })).toHaveTextContent("ינואר 2027");
    expect(new FormData(container.querySelector("form")!).get("month")).toBe("2027-01");
    fireEvent.click(screen.getByRole("button", { name: "חודש לבדיקה: החודש הקודם" }));
    expect(new FormData(container.querySelector("form")!).get("month")).toBe("2026-12");
  });

  it("browses years without selecting, cancels with Escape, then selects and restores focus", async () => {
    const onChange = vi.fn();
    render(<Picker onChange={onChange} />);
    const trigger = screen.getByRole("button", { name: "חודש לבדיקה" });
    fireEvent.click(trigger);
    await screen.findByRole("button", { name: "דצמבר 2026" });
    fireEvent.click(screen.getByRole("button", { name: "השנה הבאה" }));
    expect(screen.getByRole("button", { name: "ינואר 2027" })).toBeVisible();
    expect(trigger).toHaveTextContent("דצמבר 2026");
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByRole("button", { name: "השנה הבאה" }), { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());
    fireEvent.click(trigger);
    const selected = await screen.findByRole("button", { name: "דצמבר 2026" });
    expect(selected).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "פברואר 2026" }));
    expect(onChange).toHaveBeenCalledExactlyOnceWith("2026-02");
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("moves keyboard focus in RTL, across a year boundary, without changing the value", async () => {
    const onChange = vi.fn();
    render(<Picker onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "חודש לבדיקה" }));
    const december = await screen.findByRole("button", { name: "דצמבר 2026" });
    fireEvent.keyDown(december, { key: "ArrowLeft" });
    expect(screen.getByRole("button", { name: "ינואר 2027" })).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
    expect(screen.getByRole("button", { name: "אפריל 2027" })).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "End" });
    expect(screen.getByRole("button", { name: "יוני 2027" })).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "Home" });
    expect(screen.getByRole("button", { name: "אפריל 2027" })).toHaveFocus();
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.click(document.activeElement!);
    expect(onChange).toHaveBeenCalledExactlyOnceWith("2027-04");
  });

  it("enforces a bounded planning horizon and can clear an optional filter", async () => {
    const onChange = vi.fn();
    render(<Picker initial="2026-09" min="2026-09" max="2027-08" onChange={onChange} />);
    expect(screen.getByRole("button", { name: "חודש לבדיקה: החודש הקודם" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "חודש לבדיקה" }));
    expect(await screen.findByRole("button", { name: "אוגוסט 2026" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "השנה הקודמת" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "השנה הבאה" }));
    expect(screen.getByRole("button", { name: "ספטמבר 2027" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "השנה הבאה" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "אוגוסט 2027" }));
    expect(screen.getByRole("button", { name: "חודש לבדיקה: החודש הבא" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "חודש לבדיקה" }));
    fireEvent.click(await screen.findByRole("button", { name: "כל החודשים" }));
    expect(onChange).toHaveBeenLastCalledWith("");
    expect(screen.getByRole("button", { name: "חודש לבדיקה" })).toHaveTextContent("כל החודשים");
    expect(screen.getByRole("button", { name: "חודש לבדיקה: החודש הבא" })).toBeDisabled();
  });
});
