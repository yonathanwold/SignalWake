import type { CanonicalEvent } from "../lib/types";

export function ClassificationPill({ value }: { value: CanonicalEvent["classification"] | "LIVE" | "DEMO" }) {
  return <span className={`classification classification-${value.toLowerCase()}`}>{value}</span>;
}

export function SeverityDot({ severity }: { severity: CanonicalEvent["severity"] }) {
  return <span aria-label={`${severity} severity`} className={`severity-dot severity-${severity}`} />;
}

