import type { Metadata, Viewport } from "next";
import "@fontsource/noto-sans-hebrew/400.css";
import "@fontsource/noto-sans-hebrew/500.css";
import "@fontsource/noto-sans-hebrew/600.css";
import "./globals.css";
import { AppProvider } from "@/components/app-provider";
import { ThemeProvider } from "@/components/theme-provider";

export const metadata: Metadata = {
  title: { default: "FamilyFin", template: "%s · FamilyFin" },
  description: "ניהול פיננסי משפחתי פרטי",
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, title: "FamilyFin", statusBarStyle: "default" },
  robots: { index: false, follow: false },
};

export const viewport: Viewport = { themeColor: "#f6f7f8", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="he" dir="rtl" suppressHydrationWarning>
      <body><ThemeProvider><AppProvider>{children}</AppProvider></ThemeProvider></body>
    </html>
  );
}
