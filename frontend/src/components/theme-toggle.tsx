"use client";

import { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const isDark = resolvedTheme === "dark";
  return <Button type="button" variant="outline" size="icon" aria-label={isDark ? "החלפה לערכת יום" : "החלפה לערכת לילה"} title={isDark ? "ערכת יום" : "ערכת לילה"} onClick={() => setTheme(isDark ? "light" : "dark")} disabled={!mounted}><span aria-hidden="true">{isDark ? <Sun /> : <Moon />}</span></Button>;
}
