import type { Metadata } from "next";
import "./globals.css";
import { Shell } from "../components/shell";

export const metadata: Metadata = { title: "SIGNALWAKE / Operations Console", description: "Authoritative event awareness from NWS and USGS observations." };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body><Shell>{children}</Shell></body></html>;
}

