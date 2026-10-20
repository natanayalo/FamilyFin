import type { DashboardFilters } from "./types";

// Keep report dates while navigating. AppProvider clears them before account changes.
let filters: DashboardFilters | undefined;
export const getDashboardFilters = () => filters;
export const rememberDashboardFilters = (value: DashboardFilters) => { filters = value; };
export const resetDashboardFilters = () => { filters = undefined; };
