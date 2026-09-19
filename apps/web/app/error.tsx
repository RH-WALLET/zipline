"use client";

export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="page narrow">
      <div className="callout danger" role="alert">
        <strong>Render error.</strong> <code>{error.message}</code>
        <div style={{ marginTop: 8 }}>
          <button className="tag" onClick={() => reset()} style={{ cursor: "pointer", background: "transparent" }}>
            Retry
          </button>
        </div>
      </div>
    </div>
  );
}
