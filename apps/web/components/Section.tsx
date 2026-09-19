import type { ReactNode } from "react";

/** A report section: a serif heading on a hairline, an optional monospaced note, then the body. */
export function Section({ id, title, note, children }: { id: string; title: string; note?: ReactNode; children: ReactNode }) {
  return (
    <section className="section" id={id} aria-label={title}>
      <div className="head">
        <h2>{title}</h2>
        {note ? <div className="note">{note}</div> : null}
      </div>
      {children}
    </section>
  );
}

export function Contents({ items }: { items: [string, string][] }) {
  return (
    <nav className="contents" aria-label="Contents">
      {items.map(([id, label]) => (
        <a key={id} href={`#${id}`}>
          {label}
        </a>
      ))}
    </nav>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="footnote" style={{ fontStyle: "italic" }}>{children}</p>;
}
