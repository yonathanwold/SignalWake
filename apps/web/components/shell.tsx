"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { ChevronIcon, FlaskIcon, HeartbeatIcon, HistoryIcon, LinkIcon, ListIcon, MapIcon, NetworkIcon, SignalMark } from "./icons";

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
  const [utcClock, setUtcClock] = useState("--:--");
  const [navCollapsed, setNavCollapsed] = useState(false);
  const [commandOpen, setCommandOpen] = useState(false);
  const [commandQuery, setCommandQuery] = useState("");
  const [apiState, setApiState] = useState<"CHECKING" | "LIVE" | "DEGRADED">("CHECKING");
  const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
  useEffect(() => {
    const updateClock = () => setUtcClock(new Intl.DateTimeFormat("en-US", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC" }).format(new Date()));
    updateClock();
    const interval = window.setInterval(updateClock, 60_000);
    return () => window.clearInterval(interval);
  }, []);
  useEffect(() => {
    const stored = window.localStorage.getItem("signalwake.nav-collapsed");
    if (stored === "true") setNavCollapsed(true);
    const handleKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandOpen(true);
      }
      if (event.key === "Escape") setCommandOpen(false);
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, []);
  useEffect(() => {
    window.localStorage.setItem("signalwake.nav-collapsed", String(navCollapsed));
  }, [navCollapsed]);
  useEffect(() => {
    let cancelled = false;
    fetch(`${apiBase}/health/live`, { cache: "no-store", signal: AbortSignal.timeout(2200) })
      .then((response) => { if (!cancelled) setApiState(response.ok ? "LIVE" : "DEGRADED"); })
      .catch(() => { if (!cancelled) setApiState("DEGRADED"); });
    return () => { cancelled = true; };
  }, [apiBase]);
  const filteredNav = navItems.filter((item) => item.label.toLowerCase().includes(commandQuery.toLowerCase()));
  return <div className="app-shell">
    <header className="topbar">
      <Link className="brand" href="/" aria-label="SIGNALWAKE home"><SignalMark size={21} /><span>SIGNAL<span className="brand-accent">WAKE</span></span></Link>
      <div className="topbar-divider" />
      <div className="topbar-context"><span className="context-kicker">OPERATIONS CONSOLE</span><span className="context-slash">/</span><span>{pathname === "/" ? "Operational Map" : navItems.find((item) => item.href === pathname)?.label ?? "Signal surface"}</span></div>
      <div className="topbar-actions"><button className="command-trigger" type="button" onClick={() => { setCommandOpen(true); setCommandQuery(""); }} aria-label="Open command search"><span className="command-search-icon">⌕</span><span>SEARCH SURFACES</span><kbd>⌘K</kbd></button><span className={`connection connection-${apiState.toLowerCase()}`}><span className="connection-dot" /> API STATUS: {apiState}</span><span className="clock">UTC {utcClock}</span><span className="topbar-utility" aria-hidden="true">/</span><span className="topbar-utility">V2 CONSOLE</span></div>
    </header>
    <div className="body-shell">
      <aside className={`side-nav ${navCollapsed ? "side-nav-collapsed" : ""}`} aria-label="Primary navigation">
        <button className="side-nav-toggle" type="button" onClick={() => setNavCollapsed((collapsed) => !collapsed)} aria-expanded={!navCollapsed} aria-label={navCollapsed ? "Expand primary navigation" : "Collapse primary navigation"}><ChevronIcon size={14} /><span>{navCollapsed ? "EXPAND" : "COLLAPSE"}</span></button>
        <div className="side-nav-label">SURFACES</div>
        <nav>{navItems.map(({ href, label, icon: Icon }) => <Link key={href} href={href} title={label} aria-label={label} className={`nav-item ${pathname === href ? "nav-item-active" : ""}`}><Icon size={16} /><span>{label}</span>{pathname === href && <span className="nav-active-mark" />}</Link>)}</nav>
        <div className="side-nav-footer"><div className="footer-line" /><span>PHASE 07</span><span>DETERMINISTIC CORE</span></div>
      </aside>
      <main className="main-content">{children}</main>
    </div>
    {commandOpen && <div className="command-backdrop" role="presentation" onMouseDown={() => setCommandOpen(false)}><section className="command-palette" role="dialog" aria-modal="true" aria-label="Navigate SIGNALWAKE surfaces" onMouseDown={(event) => event.stopPropagation()}><div className="command-input-wrap"><span>⌕</span><input autoFocus value={commandQuery} onChange={(event) => setCommandQuery(event.target.value)} placeholder="Jump to a surface" aria-label="Search surfaces" /><kbd>ESC</kbd></div><div className="command-results">{filteredNav.length ? filteredNav.map(({ href, label, icon: Icon }) => <Link key={href} href={href} className="command-result" onClick={() => setCommandOpen(false)}><Icon size={15} /><span>{label}</span><span className="command-result-key">OPEN</span></Link>) : <p className="command-empty">No matching surface.</p>}</div><div className="command-foot">SIGNALWAKE V2 <span>UTC {utcClock}</span></div></section></div>}
  </div>;
}
