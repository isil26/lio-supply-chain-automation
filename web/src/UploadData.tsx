import { useEffect, useRef, useState } from "react";
import { hostedReplayBuild, type DashboardData, type Readiness } from "./api";

const CHUNK_SIZE = 1024 * 1024;
const MAX_SIZE = 64 * CHUNK_SIZE;
const ACCEPT = ".csv,.tsv,.xlsx,.pdf,.docx,.txt,.md,.json,.jpg,.jpeg,.png,.tif,.tiff,.webp,.eml,.zip";

export type UploadResult = {
  id: string;
  before: Readiness[];
  dashboard: DashboardData;
  files: { name: string; status: "ingested" | "unchanged" }[];
};

type UploadState = {
  status: "idle" | "unavailable" | "uploading" | "processing" | "ready" | "rejected";
  portal?: { configured: boolean; endpoint: string };
  report?: { name: string; files: UploadResult["files"] };
  id?: string;
  name?: string;
  error?: string;
  result?: UploadResult | null;
};

async function request(body?: object): Promise<UploadState> {
  const headers = new Headers();
  if (!hostedReplayBuild) {
    const key = "soony-upload-session";
    let session = sessionStorage.getItem(key);
    if (!session) {
      session = crypto.randomUUID();
      sessionStorage.setItem(key, session);
    }
    headers.set("X-Soony-Upload-Session", session);
  }
  if (body) headers.set("Content-Type", "application/json");
  const response = await fetch("/api/uploads", {
    cache: "no-store",
    headers,
    ...(body ? { method: "POST", body: JSON.stringify(body) } : {}),
  });
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || "Upload processing is unavailable.");
  return value;
}

function encode(chunk: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1]);
    reader.onerror = () => reject(new Error("The file could not be read."));
    reader.readAsDataURL(chunk);
  });
}

export function UploadData({ onResult }: { onResult: (result: UploadResult | null) => void }) {
  const picker = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<UploadState | null>(null);
  const [sending, setSending] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const lastResult = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (sending) return;
    let active = true;
    let timer: number;
    const refresh = async () => {
      try {
        const next = await request();
        if (!active) return;
        setState(next);
        if (lastResult.current !== next.result?.id) {
          lastResult.current = next.result?.id;
          onResult(next.result ?? null);
        }
        if (next.status === "processing") timer = window.setTimeout(refresh, 1200);
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : "Import status is unavailable.");
      }
    };
    void refresh();
    return () => { active = false; window.clearTimeout(timer); };
  }, [onResult, sending, reload]);

  const run = async (file?: File) => {
    if (file && (!file.size || file.size > MAX_SIZE)) {
      setError("Choose a nonempty file up to 64 MB.");
      return;
    }
    setSending(true);
    setError("");
    setProgress(0);
    const id = crypto.randomUUID();
    try {
      if (file) {
        for (let offset = 0; offset < file.size; offset += CHUNK_SIZE) {
          const slice = file.slice(offset, offset + CHUNK_SIZE);
          await request({ id, name: file.name, size: file.size, offset, chunk: await encode(slice) });
          setProgress(Math.round(100 * (offset + slice.size) / file.size));
        }
      } else {
        await request({ id, source: "portal" });
      }
      setState(previous => ({ ...previous, id, status: "processing", name: file?.name ?? "Challenge API" }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed.");
    } finally {
      setSending(false);
    }
  };

  const reset = async () => {
    setSending(true);
    try {
      await request({ reset: true });
      lastResult.current = undefined;
      onResult(null);
      setError("");
      window.location.hash = "dashboard";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not close the import scenario.");
    } finally {
      setSending(false);
    }
  };

  const busy = sending || state?.status === "processing";
  const disabled = !state || state.status === "unavailable" || busy;
  const report = state?.report;
  const imported = report?.files.filter(file => file.status === "ingested").length ?? 0;
  const skipped = (report?.files.length ?? 0) - imported;
  const forecastChanges = imported ? state?.result?.dashboard.readiness.flatMap(edition => {
    const before = state.result?.before.find(row => row.edition === edition.edition)?.p50;
    if (before == null || before === edition.p50 || edition.p50 == null) return [];
    return [`${edition.edition === "CE" ? "Collector’s" : "Standard"} ${before.toLocaleString()} → ${edition.p50.toLocaleString()}`];
  }) : [];

  return <div className="import-page">
    <div className="import-sources">
      <section className="card import-source">
        <svg className="source-symbol" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h9l4 4v14H6zM14 3v5h5M10 5v2m0 2v2m0 2v2"/><rect x="8.5" y="16" width="3" height="2.5" rx=".5"/></svg>
        <h2>ZIP archive</h2>
        <p>Upload the challenge ZIP or a single case file, up to 64 MB.</p>
        <input ref={picker} type="file" accept={ACCEPT} hidden onChange={event => {
          const file = event.currentTarget.files?.[0];
          event.currentTarget.value = "";
          if (file) void run(file);
        }}/>
        <div className="source-action"><button className="primary-button" disabled={disabled} onClick={() => picker.current?.click()}>Choose file or ZIP</button></div>
      </section>
      <section className="card import-source">
        <svg className="source-symbol" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5 3 12l5 7m8-14 5 7-5 7m-3-16-2 18"/></svg>
        <h2>Challenge API</h2>
        <p>Fetch the latest files from the Lio portal using the team’s server connection.</p>
        {state?.portal && <code className="import-endpoint">{state.portal.endpoint}</code>}
        <div className="source-action"><button className="ghost-button" disabled={disabled || !state?.portal?.configured} onClick={() => void run()}>Import from API</button></div>
        {state?.portal && !state.portal.configured && <small>The server needs the team portal credential.</small>}
      </section>
    </div>
    <p className="muted import-note">Both sources update your private forecast scenario. Files with identical content are skipped.</p>
    <div role="status" aria-live="polite">
      {sending ? (progress > 0 ? `Uploading · ${progress}%` : "Submitting import…") :
        state?.status === "processing" ? `Checking ${state.name}…` :
        state?.status === "uploading" ? "Upload incomplete. Choose the file again to retry." :
        state?.status === "unavailable" ? "The import service is unavailable." : !state && !error ? "Connecting to the import service…" : ""}
      {!busy && report && <section className="card import-result"><h2>Last completed import</h2>
        <p>{report.name} · <strong>{imported} imported</strong> · {skipped} skipped</p>
        {forecastChanges && forecastChanges.length > 0 && <p>{forecastChanges.join(" · ")}</p>}
        <details><summary>File details ({report.files.length})</summary><ul>{report.files.map((file, index) =>
          <li key={index}><span>{file.name}</span><strong>{file.status === "ingested" ? "Imported" : "Skipped"}</strong></li>)}</ul></details>
      </section>}
    </div>
    {(error || state?.error) && <div className="notice alert" role="alert">{error || state?.error}
      {error && <button className="link-button" onClick={() => { setError(""); setReload(value => value + 1); }}>Refresh status</button>}
    </div>}
    {state?.result && !busy && <div className="actions"><a className="source-link" href="#dashboard">View scenario forecast</a>
      <button className="ghost-button" onClick={() => void reset()}>Close scenario</button></div>}
  </div>;
}
