import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { InsightPreferencesFeature } from "@/features/insight-preferences/insight-preferences-feature";
import * as insightApi from "@/features/insight-preferences/api";

vi.mock("@/features/insight-preferences/api", () => ({
  getInsightPreferences: vi.fn(), getInsightPreferenceOptions: vi.fn(), getInsightAlerts: vi.fn(),
  getMonthlySummaries: vi.fn(), saveInsightPreferences: vi.fn(), transitionInsightAlert: vi.fn(),
}));

const preferences = {
  planning_scenario_id: null, planning_revision_id: null, forecast_id: null, forecast_revision_id: null,
  forecast_role: null, apartment_study_id: null, apartment_revision_id: null,
  apartment_alternative_name: null, updated_at: null,
};
const alert = {
  id: "alert-1", condition_type: "stale_import", subject_identity: "latest_import", currency: null,
  evidence_period: "current", state: "open" as const, first_seen: "2026-09-20T12:00:00Z",
  last_seen: "2026-09-28T12:00:00Z", occurrence_count: 2, evidence: { freshness_days: 45 },
};

describe("Insight preferences and review", () => {
  beforeEach(() => {
    vi.mocked(insightApi.getInsightPreferences).mockResolvedValue({ data: preferences });
    vi.mocked(insightApi.getInsightPreferenceOptions).mockResolvedValue({ data: {
      planning_scenarios: [{ id: "scenario-1", name: "תכנון משפחתי", currency: "ILS", revision_number: 3 }],
      forecasts: [], apartment_studies: [],
    } });
    vi.mocked(insightApi.getInsightAlerts).mockResolvedValue({ data: { items: [alert] } });
    vi.mocked(insightApi.getMonthlySummaries).mockResolvedValue({ data: { items: [{
      id: "summary-1", revision_number: 2, month: "2026-08-01", currency: "ILS", content_hash: "hash",
      content: {}, markdown: "סיכום אוגוסט", created_at: "2026-09-01T10:00:00Z",
    }] } });
    vi.mocked(insightApi.saveInsightPreferences).mockResolvedValue({ data: {
      ...preferences, planning_scenario_id: "scenario-1", planning_revision_id: "scenario-rev-3",
    } });
    vi.mocked(insightApi.transitionInsightAlert).mockResolvedValue({ data: { ...alert, state: "acknowledged" } });
  });

  it("saves a listed scenario and exposes saved summaries and alert review controls", async () => {
    render(<InsightPreferencesFeature />);
    await screen.findByText("סיכום אוגוסט");
    expect(screen.getByText("ייבוא ישן")).toBeVisible();
    expect(screen.getByText(/ראיות/)).toBeVisible();
    fireEvent.change(screen.getByLabelText("תרחיש תכנון ראשי"), { target: { value: "scenario-1" } });
    fireEvent.click(screen.getByRole("button", { name: "שמירת העדפות" }));
    await screen.findByText("העדפות התובנות נשמרו.");
    expect(insightApi.saveInsightPreferences).toHaveBeenCalledWith(expect.objectContaining({
      planning_scenario_id: "scenario-1", planning_revision_id: null,
    }));

    fireEvent.click(screen.getByRole("button", { name: "סימון לבדיקה" }));
    await screen.findByText("התובנה סומנה לבדיקה.");
    await waitFor(() => expect(insightApi.transitionInsightAlert).toHaveBeenCalledWith("alert-1", "acknowledge"));
  });
});
