import type { ReactNode } from "react";
import { api, settle } from "@/lib/api";
import { Colophon } from "@/components/Colophon";
import { Masthead } from "@/components/Masthead";

export const dynamic = "force-dynamic";

/** The report shell: running head, the page, colophon. Every page under it is a section of the tear sheet. */
export default async function ReportLayout({ children }: { children: ReactNode }) {
  const status = await settle(api.status());
  return (
    <>
      <Masthead status={status} />
      <main>{children}</main>
      <Colophon status={status} />
    </>
  );
}
