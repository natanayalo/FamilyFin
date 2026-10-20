"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowDownLeft, ChartColumn, ChartNoAxesCombined, CircleCheck, House, Landmark, ListFilter, Menu, Settings, Sparkles, Wallet } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useAppAuth } from "@/components/app-provider";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, LoadingState, ReconnectState } from "@/components/ui/async-state";
import { NetWorthPage } from "@/features/net-worth/net-worth-page";
import { ForecastsFeature } from "@/features/forecasts/ForecastsFeature";

export const sections = [
  { id: "dashboard", href: "/dashboard", label: "סקירה", icon: ChartColumn, title: "סקירה כללית", note: "תמונת מצב של ההכנסות, ההוצאות ואיכות הנתונים." },
  { id: "expenses", href: "/expenses", label: "הוצאות", icon: ArrowDownLeft, title: "הוצאות", note: "ניתוח הוצאות, מגמות ועסקאות תורמות." },
  { id: "data-quality", href: "/data-quality", label: "איכות נתונים", icon: CircleCheck, title: "איכות נתונים וייבוא", note: "בדיקת מקורות, ייבוא קבצים והתאמות." },
  { id: "classification", href: "/classification", label: "סיווג", icon: ListFilter, title: "סיווג עסקאות", note: "תור בדיקה, תיקוני סיווג וכללים חוזרים." },
  { id: "planning", href: "/planning", label: "תכנון", icon: ChartNoAxesCombined, title: "תכנון", note: "תרחישים, גרסאות והשוואה לביצוע." },
  { id: "net-worth", href: "/net-worth", label: "הון משפחתי", icon: Landmark, title: "הון משפחתי", note: "חשבונות, תמונות מצב והיסטוריית שווי." },
  { id: "savings-forecast", href: "/savings-forecast", label: "תחזית חיסכון", icon: Wallet, title: "תחזית חיסכון", note: "תחזיות לפי תרחיש תכנון וגרסה נבחרת." },
  { id: "apartment-plan", href: "/apartment-plan", label: "תכנון דירה", icon: House, title: "תכנון רכישת דירה", note: "הכלי עדיין בפיתוח ואינו זמין לחישוב.", availability: "בפיתוח" },
  { id: "automation-insights", href: "/automation-insights", label: "תובנות ואוטומציה", icon: Sparkles, title: "תובנות ואוטומציה", note: "מצב תהליכים, התראות וסיכומים שמורים." },
  { id: "settings", href: "/settings", label: "הגדרות", icon: Settings, title: "הגדרות", note: "העדפות תצוגה, עדכניות נתונים, התראות וחיבורים." },
];

const mobilePrimaryIds = new Set(["dashboard", "expenses", "planning", "net-worth"]);
const mobileMoreGroups = [
  { label: "בדיקה וסיווג", items: ["data-quality", "classification"] },
  { label: "תכנון מתקדם", items: ["savings-forecast", "apartment-plan"] },
  { label: "ניהול", items: ["automation-insights", "settings"] },
];

function SectionLink({ id, mobile = false }: { id: string; mobile?: boolean }) {
  const pathname = usePathname();
  const item = sections.find((section) => section.id === id);
  if (!item) return null;
  const active = pathname === item.href;
  const Icon = item.icon;
  const accessibleName = `${item.label}${item.availability ? ` · ${item.availability}` : ""}`;
  return <Link href={item.href} className={`${mobile ? "mobile-nav-link" : "nav-link"}${active ? " active" : ""}`} aria-label={accessibleName} title={accessibleName} aria-current={active ? "page" : undefined}>
    <span className="nav-icon" aria-hidden="true"><Icon size={19} strokeWidth={1.7} /></span><span className={mobile ? "mobile-nav-text" : "nav-text"}>{item.label}</span>
    {item.availability && <span className="nav-availability" aria-hidden="true">{item.availability}</span>}
  </Link>;
}

export function Workspace({ sectionId = "dashboard", children }: { sectionId?: string; children?: ReactNode }) {
  const { auth, online, signOut } = useAppAuth();
  const pathname = usePathname();
  const [signOutError, setSignOutError] = useState("");
  const [moreOpen, setMoreOpen] = useState(false);
  const moreButtonRef = useRef<HTMLButtonElement>(null);
  const section = sections.find((item) => item.id === sectionId) ?? sections[0];
  const session = auth.status === "signed-in" ? auth.session : auth.status === "offline" ? auth.session : undefined;

  useEffect(() => setMoreOpen(false), [pathname]);

  function handleMoreKeys(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape" && moreOpen) {
      setMoreOpen(false);
      moreButtonRef.current?.focus();
    }
  }

  if (auth.status === "loading") return <main className="loading-screen"><LoadingState label="בודקים את החיבור המאובטח…" /></main>;

  return <div className={`app-layout${sectionId === "dashboard" ? " workspace-overview" : sectionId === "classification" ? " workspace-classification" : sectionId === "expenses" ? " workspace-expenses" : ""}`}>
    <aside className="sidebar desktop-sidebar">
      <Link className="brand" href="/" aria-label="FamilyFin - סקירה"><span className="brand-mark" aria-hidden="true"><House size={22} strokeWidth={1.7} /></span><div className="brand-word"><div className="brand-title">FamilyFin</div><div className="brand-subtitle">ניהול פיננסי משפחתי</div></div></Link>
      <nav className="desktop-navigation" aria-label="ניווט ראשי">
        <div className="nav-group"><div className="nav-label">תמונה משפחתית</div><div className="nav-list"><SectionLink id="dashboard" /><SectionLink id="expenses" /><SectionLink id="net-worth" /></div></div>
        <div className="nav-group"><div className="nav-label">תכנון</div><div className="nav-list"><SectionLink id="planning" /><SectionLink id="savings-forecast" /><SectionLink id="apartment-plan" /></div></div>
        <div className="nav-group"><div className="nav-label">בדיקה וניהול</div><div className="nav-list"><SectionLink id="data-quality" /><SectionLink id="classification" /><SectionLink id="automation-insights" /><SectionLink id="settings" /></div></div>
      </nav>
      <div className="sidebar-foot">מרחב פרטי למשפחה<br />נתונים נטענים מהשרת בלבד</div>
    </aside>
    <div className="main-column">
      {!online && <div className="offline-banner" role="alert">החיבור נותק. הנתונים והפעולות חסומים עד לחיבור מחדש.</div>}
      <header className="topbar"><div><div className="topbar-kicker">המרחב המשפחתי</div><div className="topbar-title">{sectionId === "dashboard" ? "FamilyFin" : section.title}</div></div><div className="topbar-actions">
        <div className="connection-pill" data-state={online ? "online" : "offline"} aria-label={`מצב שירות FamilyFin: ${online ? "מחובר" : "לא זמין"}`}><span className="status-dot" aria-hidden="true" />{online ? "מחובר" : "מנותק"}</div><ThemeToggle />
        {session && <div className="user-chip"><span className="avatar">{session.user.display_name.slice(0, 1)}</span><span className="user-name">{session.user.display_name}</span></div>}
        {auth.status === "signed-in" && <Button className="logout" variant="ghost" size="sm" onClick={async () => { setSignOutError(""); try { await signOut(); } catch { setSignOutError("לא ניתן לאשר יציאה מול השרת. נסו שוב."); } }}>יציאה</Button>}
      </div></header>
      {signOutError && <div className="offline-banner" role="alert">{signOutError}</div>}
      <main className="content">
        {sectionId !== "dashboard" && <div className="page-heading"><div><div className="eyebrow">FamilyFin · מרחב משפחתי</div><h1>{section.title}</h1><p>{section.note}</p></div></div>}
        {!online || auth.status === "offline" ? <ReconnectState /> : auth.status === "signed-out" ? <EmptyState title="החיבור לחשבון הסתיים" description="התחברו מחדש כדי להמשיך לצפות בנתונים." action={<Link className="secondary-button" href="/">חזרה להתחברות</Link>} /> : sectionId === "net-worth" ? <NetWorthPage /> : sectionId === "savings-forecast" ? <ForecastsFeature /> : sectionId === "apartment-plan" ? <Card className="module-card"><EmptyState title="תכנון דירה עדיין אינו זמין" description="מחשבון הרכישה והמשכנתה עדיין בפיתוח. בינתיים אפשר לבדוק את ההון הקיים ולתכנן את התקציב החודשי." action={<div className="unavailable-actions"><Link className="secondary-button" href="/net-worth">בדיקת ההון המשפחתי</Link><Link className="secondary-button" href="/planning">תכנון התקציב</Link></div>} /></Card> : children ?? <Card className="module-card"><div className="module-placeholder"><div><strong>המסך עדיין בפיתוח</strong>{section.note}<br />הכלים יוצגו כאן כשהמסך יהיה זמין.</div></div></Card>}
        <Card className="status-strip"><span className="info-symbol" aria-hidden="true">i</span><span>הנתונים הפיננסיים אינם נשמרים בדפדפן לשימוש ללא חיבור לשירות. הם מוצגים כשהחיבור לשירות FamilyFin פעיל ומאומת.</span></Card>
      </main>
    </div>
    <nav className="mobile-nav" aria-label="ניווט ראשי במכשיר נייד" onKeyDown={handleMoreKeys}>
      {Array.from(mobilePrimaryIds, (id) => <SectionLink key={id} id={id} mobile />)}
      <div className="mobile-more-wrap">
        <Button ref={moreButtonRef} className={`mobile-more-trigger${moreOpen ? " active" : ""}`} variant="ghost" aria-expanded={moreOpen} aria-controls="mobile-more-panel" onClick={() => setMoreOpen((open) => !open)}>
          <Menu aria-hidden="true" /><span>עוד</span>
        </Button>
        <div className="mobile-more-panel" id="mobile-more-panel" hidden={!moreOpen}>
          <div className="mobile-more-heading">עוד מסכים</div>
          {mobileMoreGroups.map((group) => <section className="mobile-more-group" key={group.label} aria-label={group.label}><h2>{group.label}</h2>{group.items.map((id) => <SectionLink key={id} id={id} mobile />)}</section>)}
        </div>
      </div>
    </nav>
  </div>;
}
