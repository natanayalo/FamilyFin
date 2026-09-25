"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { useAppAuth } from "@/components/app-provider";
import { EmptyState, LoadingState, ReconnectState } from "@/components/ui/async-state";

export const sections = [
  { id: "dashboard", href: "/", label: "סקירה", icon: "◫", title: "סקירה כללית", note: "תמונת מצב של ההכנסות, ההוצאות ואיכות הנתונים." },
  { id: "expenses", href: "/expenses", label: "הוצאות", icon: "↘", title: "הוצאות", note: "ניתוח הוצאות, מגמות ועסקאות תורמות." },
  { id: "data-quality", href: "/data-quality", label: "איכות נתונים", icon: "✓", title: "איכות נתונים וייבוא", note: "בדיקת מקורות, ייבוא קבצים והתאמות." },
  { id: "classification", href: "/classification", label: "סיווג", icon: "≡", title: "סיווג עסקאות", note: "תור בדיקה, תיקוני סיווג וכללים חוזרים." },
  { id: "planning", href: "/planning", label: "תכנון", icon: "⌁", title: "תכנון", note: "תרחישים, גרסאות והשוואה לביצוע." },
  { id: "net-worth", href: "/net-worth", label: "הון משפחתי", icon: "◈", title: "הון משפחתי", note: "חשבונות, תמונות מצב והיסטוריית שווי." },
  { id: "savings-forecast", href: "/savings-forecast", label: "תחזית חיסכון", icon: "⌇", title: "תחזית חיסכון", note: "תחזיות לפי תרחיש תכנון וגרסה נבחרת." },
  { id: "apartment-plan", href: "/apartment-plan", label: "תכנון דירה", icon: "⌂", title: "תכנון רכישת דירה", note: "חלופות רכישה, מקורות מימון ומשכנתה." },
  { id: "automation-insights", href: "/automation-insights", label: "תובנות ואוטומציה", icon: "✳", title: "תובנות ואוטומציה", note: "מצב תהליכים, התראות וסיכומים שמורים." },
];

export function Workspace({ sectionId = "dashboard" }: { sectionId?: string }) {
  const { auth, online, signOut } = useAppAuth();
  const pathname = usePathname();
  const [signOutError, setSignOutError] = useState("");
  const section = sections.find((item) => item.id === sectionId) ?? sections[0];
  if (auth.status === "loading") return <main className="loading-screen"><LoadingState label="בודקים את החיבור המאובטח…" /></main>;

  return (
    <div className="app-layout">
      <aside className="sidebar">
        <Link className="brand" href="/" aria-label="FamilyFin — סקירה"><span className="brand-mark" aria-hidden="true">⌂</span><div className="brand-word"><div className="brand-title">FamilyFin</div><div className="brand-subtitle">ניהול פיננסי משפחתי</div></div></Link>
        <nav aria-label="ניווט ראשי"><div className="nav-label">המרחב המשפחתי</div><div className="nav-list">{sections.map((item) => <Link key={item.id} href={item.href} className={`nav-link${pathname === item.href ? " active" : ""}`} aria-current={pathname === item.href ? "page" : undefined}><span className="nav-icon" aria-hidden="true">{item.icon}</span><span className="nav-text">{item.label}</span></Link>)}</div></nav>
        <div className="sidebar-foot">מרחב פרטי למשפחה<br />נתונים נטענים מהשרת בלבד</div>
      </aside>
      <div className="main-column">
        {!online && <div className="offline-banner" role="alert">החיבור נותק. הנתונים והפעולות חסומים עד לחיבור מחדש.</div>}
        <header className="topbar"><div><div className="topbar-kicker">המרחב המשפחתי</div><div className="topbar-title">{section.title}</div></div><div className="topbar-actions"><div className="connection-pill"><span className="status-dot" />{online ? "מחובר" : "מנותק"}</div>{auth.status === "signed-in" && <><div className="user-chip"><span className="avatar">{auth.session.user.display_name.slice(0, 1)}</span><span className="user-name">{auth.session.user.display_name}</span></div><button className="logout" onClick={async () => { setSignOutError(""); try { await signOut(); } catch { setSignOutError("לא ניתן לאשר יציאה מול השרת. נסו שוב."); } }}>יציאה</button></>}</div></header>
        {signOutError && <div className="offline-banner" role="alert">{signOutError}</div>}
        <main className="content">
          <div className="page-heading"><div><div className="eyebrow">FamilyFin · מרחב משפחתי</div><h1>{section.title}</h1><p>{section.note}</p></div></div>
          {!online || auth.status === "offline" ? <ReconnectState /> : auth.status === "signed-out" ? <EmptyState title="החיבור לחשבון הסתיים" description="התחברו מחדש כדי להמשיך לצפות בנתונים." action={<Link className="secondary-button" href="/">חזרה להתחברות</Link>} /> : <section className="surface module-card"><div className="module-placeholder"><div><strong>המסך מוכן לחיבור לשירות</strong>{section.note}<br />הנתונים יוצגו כאן לאחר חיבור מודול ה‑API המתאים.</div></div></section>}
          <div className="surface status-strip"><span className="info-symbol" aria-hidden="true">i</span><span>המסך הזה אינו שומר מידע בדפדפן. כל נתון פיננסי זמין רק בחיבור מקוון מאומת.</span></div>
        </main>
      </div>
    </div>
  );
}
