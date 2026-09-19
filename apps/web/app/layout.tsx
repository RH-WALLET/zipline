import type { Metadata } from "next";
import { Red_Hat_Mono, Source_Serif_4 } from "next/font/google";
import type { ReactNode } from "react";
import "./globals.css";
import { api, settle } from "@/lib/api";
import { Colophon } from "@/components/Colophon";
import { Masthead } from "@/components/Masthead";

const serif = Source_Serif_4({ subsets: ["latin"], weight: ["400", "600", "700"], style: ["normal", "italic"], variable: "--font-source-serif", display: "swap" });
const mono = Red_Hat_Mono({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-red-hat-mono", display: "swap" });

export const metadata: Metadata = {
  title: "ZIPLINE — live tear sheet",
  description: "The open-source Quantopian engine, reconnected to real markets on Robinhood Chain. Ten deterministic strategies, one treasury, real Stock Token trades.",
};

export const dynamic = "force-dynamic";

export default async function RootLayout({ children }: { children: ReactNode }) {
  const status = await settle(api.status());
  return (
    <html lang="en" className={`${serif.variable} ${mono.variable}`}>
      <body>
        <Masthead status={status} />
        <main>{children}</main>
        <Colophon status={status} />
      </body>
    </html>
  );
}
