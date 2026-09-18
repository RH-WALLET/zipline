"use client";

import { useEffect, useState, type ReactNode } from "react";

export type Tab = { id: string; label: string; count?: number | string; content: ReactNode };

/** Quantopian-style report tabs. All panes are rendered (hidden), so the page stays searchable. */
export function Tabs({ tabs, initial }: { tabs: Tab[]; initial?: string }) {
  const first = initial ?? tabs[0]?.id;
  const [active, setActive] = useState<string>(first);

  useEffect(() => {
    const fromHash = () => {
      const h = window.location.hash.replace("#", "");
      if (h && tabs.some((t) => t.id === h)) setActive(h);
    };
    fromHash();
    window.addEventListener("hashchange", fromHash);
    return () => window.removeEventListener("hashchange", fromHash);
  }, [tabs]);

  return (
    <div>
      <div className="tabs" role="tablist">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={active === t.id}
            aria-controls={`panel-${t.id}`}
            onClick={() => {
              setActive(t.id);
              history.replaceState(null, "", `#${t.id}`);
            }}
          >
            {t.label}
            {t.count !== undefined ? <span className="count">{t.count}</span> : null}
          </button>
        ))}
      </div>
      {tabs.map((t) => (
        <div key={t.id} id={`panel-${t.id}`} role="tabpanel" aria-labelledby={`tab-${t.id}`} className="tabpanel" hidden={active !== t.id}>
          {t.content}
        </div>
      ))}
    </div>
  );
}
