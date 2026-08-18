import Link from "next/link";
import { ChevronIcon, LinkIcon } from "../../components/icons";
import { GraphWorkspace } from "../../components/graph-workspace";
import { ScenarioLab } from "../../components/scenario-lab";
import { ReplayWorkspace } from "../../components/replay-workspace";
import { ProvenanceWorkspace } from "../../components/provenance-workspace";

const details: Record<string, { title: string; kicker: string; body: string; next: string }> = {
  infrastructure: { title: "Infrastructure Graph", kicker: "DEPENDENCY CONTEXT", body: "Relationship-aware infrastructure context is not connected in Phase 01. This surface will consume canonical events once authoritative asset data and topology are available.", next: "Connect asset registry" },
  scenario: { title: "Scenario Lab", kicker: "DETERMINISTIC EXPLORATION", body: "Scenario simulation is intentionally unavailable until a versioned, source-backed ruleset is defined. No impact claims are generated here.", next: "Define scenario rules" },
  replay: { title: "Historical Replay", kicker: "TEMPORAL CONTEXT", body: "Scrub a bounded, UTC knowledge-time projection without mixing later observations into an earlier state.", next: "Open replay" },
  provenance: { title: "Source Provenance", kicker: "CHAIN OF CUSTODY", body: "Trace source observations through normalized objects and deterministic transformations.", next: "Open Event Feed" },
  health: { title: "System Health", kicker: "SOURCE FRESHNESS", body: "Source health is available from the API and shown in the shell. Detailed ingestion run history and alerting are not implemented in this slice.", next: "Inspect API health" },
};

export default async function FutureSurfacePage({ params }: { params: Promise<{ section: string }> }) {
  const { section } = await params;
  if (section === "infrastructure") return <GraphWorkspace />;
  if (section === "scenario" || section === "scenario-lab" || section === "scenarios") return <ScenarioLab />;
  if (section === "replay") return <ReplayWorkspace />;
  if (section === "provenance") return <ProvenanceWorkspace />;
  const detail = details[section] ?? { title: "Signal surface", kicker: "ROUTE NOT FOUND", body: "This route is not part of the current SignalWake surface map.", next: "Operational Map" };
  const href = section === "provenance" ? "/feed" : "/";
  return <div className="future-page"><div className="future-kicker">{detail.kicker}</div><h1>{detail.title}</h1><p>{detail.body}</p><div className="future-rule" /><Link className="future-link" href={href}><LinkIcon size={15} /> {detail.next.toUpperCase()} <ChevronIcon size={14} /></Link><div className="future-status"><span className="future-status-dot" /> PHASE 01 / SURFACE REGISTERED <span>—</span> NO SIMULATED ANALYTICS</div></div>;
}
