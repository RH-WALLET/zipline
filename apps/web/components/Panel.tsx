import type { ReactNode } from "react";

/** A white report panel with a titled header. */
export function Panel({ title, meta, children, className = "", id, flush = false, foot }: { title: string; meta?: ReactNode; children: ReactNode; className?: string; id?: string; flush?: boolean; foot?: ReactNode }) {
  return (
    <section className={`panel ${className}`} id={id} aria-label={title}>
      <div className="head">
        <h2>{title}</h2>
        {meta ? <div className="note">{meta}</div> : null}
      </div>
      <div className={`body ${flush ? "flush" : ""}`}>{children}</div>
      {foot ? <div className="foot">{foot}</div> : null}
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="help" style={{ padding: "12px 16px", margin: 0 }}>{children}</p>;
}
