"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { FlaskIcon, HeartbeatIcon, HistoryIcon, LinkIcon, ListIcon, MapIcon, NetworkIcon, SignalMark } from "./icons";

const navItems = [
  { href: "/", label: "Operational Map", icon: MapIcon },
  { href: "/feed", label: "Event Feed", icon: ListIcon },
  { href: "/infrastructure", label: "Infrastructure Graph", icon: NetworkIcon },
  { href: "/scenario", label: "Scenario Lab", icon: FlaskIcon },
  { href: "/replay", label: "Historical Replay", icon: HistoryIcon },
  { href: "/provenance", label: "Source Provenance", icon: LinkIcon },
  { href: "/health", label: "System Health", icon: HeartbeatIcon },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return <div className="app-shell">
    <header className="topbar">
      <Link className="brand" href="/" aria-label="SIGNALWAKE home"><SignalMark size={21} /><span>SIGNAL<span className="brand-accent">WAKE</span></span></Link>
      <div className="topbar-divider" />
      <div className="topbar-context"><span className="context-kicker">OPERATIONS CONSOLE</span><span className="context-slash">/</span><span>{pathname === "/" ? "Operational Map" : navItems.find((item) => item.href === pathname)?.label ?? "Signal surface"}</span></div>
      <div className="topbar-actions"><span className="connection"><span className="connection-dot" /> API CONNECTED</span><span className="clock">UTC {new Intl.DateTimeFormat("en-US", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC" }).format(new Date())}</span></div>
    </header>
    <div className="body-shell">
      <aside className="side-nav" aria-label="Primary navigation">
        <div className="side-nav-label">SURFACES</div>
        <nav>{navItems.map(({ href, label, icon: Icon }) => <Link key={href} href={href} className={`nav-item ${pathname === href ? "nav-item-active" : ""}`}><Icon size={16} /><span>{label}</span>{pathname === href && <span className="nav-active-mark" />}</Link>)}</nav>
        <div className="side-nav-footer"><div className="footer-line" /><span>PHASE 01</span><span>DETERMINISTIC CORE</span></div>
      </aside>
      <main className="main-content">{children}</main>
    </div>
  </div>;
}

