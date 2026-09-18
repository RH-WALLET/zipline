"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/** Re-renders the server page on an interval so telemetry stays current without a reload. */
export function AutoRefresh({ seconds = 60 }: { seconds?: number }) {
  const router = useRouter();
  useEffect(() => {
    const id = setInterval(() => router.refresh(), seconds * 1000);
    return () => clearInterval(id);
  }, [router, seconds]);
  return null;
}
