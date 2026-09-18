import { shortHash } from "@/lib/format";

/** Only REAL transaction hashes get a link. Dry-run records have no hash and never look like one. */
export function TxLink({ hash, url }: { hash: string | null | undefined; url: string | null | undefined }) {
  if (!hash) return <span className="muted">—</span>;
  if (!url) return <code>{shortHash(hash)}</code>;
  return (
    <a className="mono" href={url} target="_blank" rel="noopener noreferrer" title={hash}>
      {shortHash(hash)} ↗
    </a>
  );
}
