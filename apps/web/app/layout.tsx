import type { Metadata } from "next";
import { Open_Sans } from "next/font/google";
import type { ReactNode } from "react";
import "./globals.css";
import { api, settle } from "@/lib/api";
import { Footer } from "@/components/Footer";
import { ModeBar } from "@/components/ModeBar";
import { Navbar } from "@/components/Navbar";

const openSans = Open_Sans({ subsets: ["latin"], weight: ["400", "600", "700"], variable: "--font-open-sans", display: "swap" });

export const metadata: Metadata = {
  title: "ZIPLINE",
  description: "The open-source Quantopian engine, reconnected to real markets on Robinhood Chain.",
};

export const dynamic = "force-dynamic";

export default async function RootLayout({ children }: { children: ReactNode }) {
  const status = await settle(api.status());
  return (
    <html lang="en" className={openSans.variable}>
      <body>
        <Navbar status={status} />
        <ModeBar status={status} />
        <main>{children}</main>
        <Footer status={status} />
      </body>
    </html>
  );
}
