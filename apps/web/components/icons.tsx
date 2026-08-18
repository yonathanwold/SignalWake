type IconProps = { size?: number; stroke?: number };

export function SignalMark({ size = 20 }: IconProps) {
  return <svg aria-hidden="true" className="signal-mark" width={size} height={size} viewBox="0 0 20 20" fill="none"><path d="M10 2.3v3.1M10 14.6v3.1M2.3 10h3.1M14.6 10h3.1M4.55 4.55l2.2 2.2M13.25 13.25l2.2 2.2M15.45 4.55l-2.2 2.2M6.75 13.25l-2.2 2.2" stroke="currentColor" strokeWidth="1.45" strokeLinecap="round"/><circle cx="10" cy="10" r="3.15" stroke="currentColor" strokeWidth="1.45"/></svg>;
}

export function MapIcon({ size = 16 }: IconProps) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none"><path d="m9 18-6 3V6l6-3 6 3 6-3v15l-6 3-6-3Zm0 0V3m6 3v15" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round"/></svg>;
}
export function ListIcon({ size = 16 }: IconProps) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" stroke="currentColor" strokeWidth="2.1" strokeLinecap="round"/></svg>;
}
export function NetworkIcon({ size = 16 }: IconProps) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none"><circle cx="5" cy="12" r="2.2" stroke="currentColor" strokeWidth="1.5"/><circle cx="18.5" cy="6" r="2.2" stroke="currentColor" strokeWidth="1.5"/><circle cx="18.5" cy="18" r="2.2" stroke="currentColor" strokeWidth="1.5"/><path d="m7.1 11.1 9.3-4.2M7.1 12.9l9.3 4.2" stroke="currentColor" strokeWidth="1.5"/></svg>;
}
export function FlaskIcon({ size = 16 }: IconProps) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none"><path d="M9 3h6M10 3v6.5l-5.1 8.2A2.2 2.2 0 0 0 6.75 21h10.5a2.2 2.2 0 0 0 1.85-3.3L14 9.5V3M8.2 15h7.6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>;
}
export function HistoryIcon({ size = 16 }: IconProps) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none"><path d="M3 12a9 9 0 1 0 2.63-6.36L3 8.28M3 4v4.28h4.28M12 7v5l3.2 1.9" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>;
}
export function PlayIcon({ size = 16 }: IconProps) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none"><path d="m8 5 11 7-11 7V5Z" fill="currentColor"/></svg>;
}
export function PauseIcon({ size = 16 }: IconProps) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none"><path d="M7 5h3v14H7V5Zm7 0h3v14h-3V5Z" fill="currentColor"/></svg>;
}
export function LinkIcon({ size = 16 }: IconProps) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none"><path d="M10.2 13.8a4 4 0 0 0 5.65.05l2.9-2.9a4 4 0 0 0-5.65-5.65L11.45 7M13.8 10.2a4 4 0 0 0-5.65-.05l-2.9 2.9a4 4 0 0 0 5.65 5.65l1.65-1.65" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/></svg>;
}
export function HeartbeatIcon({ size = 16 }: IconProps) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none"><path d="M3 12h4l2.1-5 3.1 10 2.1-5H21" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>;
}
export function RefreshIcon({ size = 15 }: IconProps) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none"><path d="M20 11a8 8 0 0 0-14.8-4L3 10M3 5v5h5M4 13a8 8 0 0 0 14.8 4L21 14m0 5v-5h-5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"/></svg>;
}
export function ChevronIcon({ size = 14, stroke = 1.8 }: IconProps) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none"><path d="m9 18 6-6-6-6" stroke="currentColor" strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round"/></svg>;
}
export function CloseIcon({ size = 16 }: IconProps) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none"><path d="m6 6 12 12M18 6 6 18" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"/></svg>;
}
export function AlertIcon({ size = 15 }: IconProps) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none"><path d="m12 3 9 17H3L12 3Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round"/><path d="M12 9v5m0 3h.01" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg>;
}
export function QuakeIcon({ size = 15 }: IconProps) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none"><path d="m3 14 4-4 3 3 3-6 3 4 5-1" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"/><path d="M3 19h18" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/></svg>;
}
