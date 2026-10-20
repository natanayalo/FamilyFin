import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Workspace, sections } from "@/components/workspace";

vi.mock("next/navigation", () => ({ usePathname: () => "/apartment-plan" }));
vi.mock("@/components/theme-toggle", () => ({ ThemeToggle: () => null }));
vi.mock("@/components/app-provider", () => ({ useAppAuth: () => ({ auth: { status: "signed-in", session: { user: { display_name: "QA" } } }, online: true, signOut: vi.fn() }) }));

describe("workspace navigation", () => {
  it("keeps every tablet destination named when the visible labels are hidden", () => {
    render(<><style>{".nav-text{display:none}"}</style><Workspace sectionId="apartment-plan" /></>);
    const navigation = within(screen.getByRole("navigation", { name: "ניווט ראשי" }));
    for (const section of sections) {
      const name = `${section.label}${section.availability ? ` · ${section.availability}` : ""}`;
      expect(navigation.getByRole("link", { name })).toHaveAttribute("href", section.href);
    }
  });

  it("announces apartment availability before desktop/mobile navigation and offers working alternatives", () => {
    render(<Workspace sectionId="apartment-plan" />);
    expect(screen.getByRole("link", { name: "תכנון דירה · בפיתוח" })).toHaveAttribute("title", "תכנון דירה · בפיתוח");
    fireEvent.click(screen.getByRole("button", { name: "עוד" }));
    expect(screen.getAllByRole("link", { name: "תכנון דירה · בפיתוח" })).toHaveLength(2);
    expect(screen.getByRole("heading", { name: "תכנון דירה עדיין אינו זמין" })).toBeVisible();
    expect(screen.getByRole("link", { name: "בדיקת ההון המשפחתי" })).toHaveAttribute("href", "/net-worth");
    expect(screen.getByRole("link", { name: "תכנון התקציב" })).toHaveAttribute("href", "/planning");
    fireEvent.keyDown(screen.getByRole("button", { name: "עוד" }), { key: "Escape" });
    expect(screen.getByRole("button", { name: "עוד" })).toHaveFocus();
    expect(screen.getAllByRole("link", { name: "תכנון דירה · בפיתוח" })).toHaveLength(1);
  });
});
