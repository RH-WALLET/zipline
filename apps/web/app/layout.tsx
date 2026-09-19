import type { Metadata } from "next";
import { Red_Hat_Mono, Source_Serif_4 } from "next/font/google";
import type { ReactNode } from "react";
import "./globals.css";

const serif = Source_Serif_4({ subsets: ["latin"], weight: ["400", "600", "700"], style: ["normal", "italic"], variable: "--font-source-serif", display: "swap" });
const mono = Red_Hat_Mono({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-red-hat-mono", display: "swap" });

export const metadata: Metadata = {
  title: "ZIPLINE — live tear sheet",
  description: "The open-source Quantopian engine, reconnected to real markets on Robinhood Chain. Ten deterministic strategies, one treasury, real Stock Token trades.",
};

export const dynamic = "force-dynamic";

/** Root: fonts and the document only. The report shell and the terminal shell are route-group layouts. */
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${serif.variable} ${mono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
