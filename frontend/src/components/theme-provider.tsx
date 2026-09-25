"use client";

import { ThemeProvider as NextThemeProvider } from "next-themes";

export function ThemeProvider({ children }: Readonly<{ children: React.ReactNode }>) {
  return <NextThemeProvider attribute="class" defaultTheme="system" enableSystem storageKey="familyfin-theme" disableTransitionOnChange>{children}</NextThemeProvider>;
}
