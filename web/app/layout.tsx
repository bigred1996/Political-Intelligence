import type { Metadata } from "next";
import { Public_Sans, Source_Serif_4, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { AppSidebar } from "@/components/app-sidebar";
import { AppTopBar } from "@/components/app-topbar";

const sourceSerif = Source_Serif_4({
  variable: "--font-source-serif",
  subsets: ["latin"],
  weight: ["400", "600", "700"],
  display: "swap",
});

const publicSans = Public_Sans({
  variable: "--font-public-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

const mono = JetBrains_Mono({
  variable: "--font-mono-data",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Nessus — Intelligence Platform",
  description:
    "Nessus Intelligence: institutional-grade Canadian political & regulatory intelligence — sector, region and entity risk decoded across federal data.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className={`${sourceSerif.variable} ${publicSans.variable} ${mono.variable} h-full`}
    >
      <head>
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200&display=swap"
        />
      </head>
      <body className="h-screen overflow-hidden bg-background text-on-surface app-shell flex">
        <AppSidebar />
        <div className="flex flex-col flex-1 min-w-0 h-screen">
          <AppTopBar />
          <main className="flex-1 overflow-y-auto main-scroll p-margin-mobile md:p-margin-desktop">
            <div className="mx-auto w-full max-w-[1440px]">{children}</div>
          </main>
        </div>
      </body>
    </html>
  );
}
