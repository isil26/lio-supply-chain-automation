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

function importId() {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, "0")).join("");
}

let tabSession: string;
function sessionId() {
  if (tabSession) return tabSession;
  try {
    const key = "soony-upload-session";
    tabSession = sessionStorage.getItem(key) || importId();
    sessionStorage.setItem(key, tabSession);
  } catch {
    tabSession ||= importId();
  }
  return tabSession;
}

async function request(body?: object): Promise<UploadState> {
  const headers = new Headers();
  if (!hostedReplayBuild) headers.set("X-Soony-Upload-Session", sessionId());
  if (body) headers.set("Content-Type", "application/json");
  const response = await fetch("/api/uploads", {
    cache: "no-store",
    headers,
    ...(body ? { method: "POST", body: JSON.stringify(body) } : {}),
  });
  const value = await response.json().catch(() => null);
  if (!response.ok || !value?.status) throw new Error(value?.error || "The import service is unavailable. Try again.");
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
  const [operation, setOperation] = useState<"file" | "portal" | "close" | null>(null);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");
  const [statusError, setStatusError] = useState("");
  const [checking, setChecking] = useState(true);
  const [reload, setReload] = useState(0);
  const lastResult = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (operation) return;
    let active = true;
    let timer: number;
    const refresh = async () => {
      try {
        const next = await request();
        if (!active) return;
        setState(next);
        setStatusError("");
        if (lastResult.current !== next.result?.id) {
          lastResult.current = next.result?.id;
          onResult(next.result ?? null);
        }
        if (next.status === "processing") timer = window.setTimeout(refresh, 1200);
      } catch (err) {
        if (active) setStatusError(err instanceof Error ? err.message : "Import status is unavailable.");
      } finally {
        if (active) setChecking(false);
      }
    };
    void refresh();
    return () => { active = false; window.clearTimeout(timer); };
  }, [onResult, operation, reload]);

  const run = async (file?: File) => {
    if (disabled) return;
    if (file && (!file.size || file.size > MAX_SIZE)) {
      setError("Choose a nonempty file up to 64 MB.");
      return;
    }
    setOperation(file ? "file" : "portal");
    setError("");
    setProgress(0);
    try {
      const id = importId();
      if (file) {
        for (let offset = 0; offset < file.size; offset += CHUNK_SIZE) {
          const slice = file.slice(offset, offset + CHUNK_SIZE);
          await request({ id, name: file.name, size: file.size, offset, chunk: await encode(slice) });
          setProgress(Math.round(100 * (offset + slice.size) / file.size));
        }
      } else {
        await request({ id, source: "portal" });
      }
      setState(previous => ({ ...previous, id, status: "processing", name: file?.name ?? "Challenge API", error: undefined }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed.");
    } finally {
      setChecking(true);
      setOperation(null);
    }
  };

  const reset = async () => {
    if (disabled) return;
    setOperation("close");
    setError("");
    try {
      await request({ reset: true });
      setState(previous => ({ status: "idle", portal: previous?.portal }));
      lastResult.current = undefined;
      onResult(null);
      if (window.location.hash.split("?")[0] === "#import") window.location.hash = "dashboard";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not close the import scenario.");
    } finally {
      setChecking(true);
      setOperation(null);
    }
  };

  const busy = Boolean(operation) || state?.status === "processing";
  const disabled = !state || state.status === "unavailable" || Boolean(statusError) || checking || busy;
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
    <div role="status">
      {operation === "close" ? "Closing scenario…" :
        operation === "file" ? `Uploading file · ${progress}%` :
        operation === "portal" ? "Starting the API import…" :
        checking ? "Checking import status…" : statusError ? "" :
        state?.status === "processing" ? `Processing ${state.name || "import"}…` :
        state?.status === "uploading" ? "Upload incomplete. Choose the file again to retry." :
        state?.status === "unavailable" ? "The import service is unavailable." :
        state?.status === "ready" && report ? "Import complete." : ""}
    </div>
    {!busy && report && <section className="card import-result"><h2>Last completed import</h2>
      <p>{report.name} · <strong>{imported} imported</strong> · {skipped} skipped</p>
      {forecastChanges && forecastChanges.length > 0 && <p>{forecastChanges.join(" · ")}</p>}
      <details><summary>File details ({report.files.length})</summary><ul>{report.files.map((file, index) =>
        <li key={index}><span>{file.name}</span><strong>{file.status === "ingested" ? "Imported" : "Skipped"}</strong></li>)}</ul></details>
    </section>}
    {!operation && (error || state?.error) && <div className="notice alert" role="alert">{error || state?.error}</div>}
    {statusError && <p className="notice alert" role="alert">{statusError}</p>}
    {(statusError || state?.status === "unavailable") && <button className="link-button" disabled={checking} onClick={() => {
      setChecking(true);
      setReload(value => value + 1);
    }}>Refresh status</button>}
    {state?.result && <div className="actions">{!busy && <a className="source-link" href="#dashboard">View scenario forecast</a>}
      <button className="ghost-button" disabled={disabled} onClick={() => void reset()}>Close scenario</button></div>}
  </div>;
}
