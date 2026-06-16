import type { Metadata } from "next";
import { IBM_Plex_Mono, Playfair_Display, Source_Sans_3 } from "next/font/google";
import "./globals.css";
import { AppSidebar } from "@/components/app-sidebar";
import { AppTopBar } from "@/components/app-topbar";
import { AppTicker } from "@/components/app-ticker";

const playfair = Playfair_Display({
  variable: "--font-playfair",
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  display: "swap",
});

const sourceSans = Source_Sans_3({
  variable: "--font-source",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  display: "swap",
});

const mono = IBM_Plex_Mono({
  variable: "--font-mono-data",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Polaris — Political Intelligence Terminal",
  description:
    "Premium Canadian political intelligence: sector, region and entity risk decoded across federal data.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className={`${playfair.variable} ${sourceSans.variable} ${mono.variable} h-full`}
    >
      <body className="h-screen flex flex-col overflow-hidden bg-canvas text-fg">
        <AppTopBar />
        <div className="flex flex-1 min-h-0">
          <AppSidebar />
          <main className="flex-1 overflow-y-auto">{children}</main>
        </div>
        <AppTicker />
      </body>
    </html>
  );
}
