export function Unavailable({ what = "Engine" }: { what?: string }) {
  return (
    <div className="callout danger" role="alert">
      <strong>{what} unavailable.</strong> The engine API did not answer. Start it with <code>docker compose up</code> or <code>zl serve</code>, then reload. Nothing here is cached or invented while it is down.
    </div>
  );
}
