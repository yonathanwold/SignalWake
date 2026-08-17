import Link from "next/link";
import { ChevronIcon, LinkIcon } from "../../components/icons";

const details: Record<string, { title: string; kicker: string; body: string; next: string }> = {
  infrastructure: { title: "Infrastructure Graph", kicker: "DEPENDENCY CONTEXT", body: "Relationship-aware infrastructure context is not connected in Phase 01. This surface will consume canonical events once authoritative asset data and topology are available.", next: "Connect asset registry" },
  scenario: { title: "Scenario Lab", kicker: "DETERMINISTIC EXPLORATION", body: "Scenario simulation is intentionally unavailable until a versioned, source-backed ruleset is defined. No impact claims are generated here.", next: "Define scenario rules" },
  replay: { title: "Historical Replay", kicker: "TEMPORAL CONTEXT", body: "Historical replay will be enabled after event retention and replay checkpoints are established. Current data is the live/demo operational slice only.", next: "Establish retention" },
  provenance: { title: "Source Provenance", kicker: "CHAIN OF CUSTODY", body: "Every event already carries source record IDs, payload hashes, adapter versions, and raw observation references. A dedicated audit surface is the next step.", next: "Open Event Feed" },
  health: { title: "System Health", kicker: "SOURCE FRESHNESS", body: "Source health is available from the API and shown in the shell. Detailed ingestion run history and alerting are not implemented in this slice.", next: "Inspect API health" },
};

export default async function FutureSurfacePage({ params }: { params: Promise<{ section: string }> }) {
  const { section } = await params;
  const detail = details[section] ?? { title: "Signal surface", kicker: "ROUTE NOT FOUND", body: "This route is not part of the current SignalWake surface map.", next: "Operational Map" };
  const href = section === "provenance" ? "/feed" : "/";
  return <div className="future-page"><div className="future-kicker">{detail.kicker}</div><h1>{detail.title}</h1><p>{detail.body}</p><div className="future-rule" /><Link className="future-link" href={href}><LinkIcon size={15} /> {detail.next.toUpperCase()} <ChevronIcon size={14} /></Link><div className="future-status"><span className="future-status-dot" /> PHASE 01 / SURFACE REGISTERED <span>—</span> NO SIMULATED ANALYTICS</div></div>;
}

