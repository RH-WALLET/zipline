"use client";

export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="container narrow">
      <div className="callout danger" role="alert">
        <strong>Render error.</strong> <code>{error.message}</code>
        <div style={{ marginTop: 8 }}>
          <button className="pill" onClick={() => reset()} style={{ cursor: "pointer" }}>
            Retry
          </button>
        </div>
      </div>
    </div>
  );
}
