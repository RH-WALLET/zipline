export default function Loading() {
  return (
    <div className="page">
      <p className="footnote" role="status" aria-live="polite" style={{ fontStyle: "italic" }}>
        reading engine state…
      </p>
    </div>
  );
}
