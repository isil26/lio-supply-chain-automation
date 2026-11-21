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
  const [state, setState] = useState<UploadState>({ status: "unavailable" });
  const [sending, setSending] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");
  const lastResult = useRef<string | undefined>(undefined);

  useEffect(() => {
    let active = true;
    let timer: number;
    const refresh = async () => {
      try {
        const next = await request();
        if (!active) return;
        setState(next);
        if (next.result && lastResult.current !== next.result.id) {
          lastResult.current = next.result.id;
          onResult(next.result);
        }
        if (next.status === "processing") timer = window.setTimeout(refresh, 900);
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : "Upload status is unavailable.");
      }
    };
    void refresh();
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [onResult, sending]);

  const upload = async (file: File) => {
    if (!file.size || file.size > MAX_SIZE) {
      setError("Choose a nonempty file up to 64 MB.");
      return;
    }
    const id = crypto.randomUUID();
    setError("");
    setProgress(0);
    setSending(true);
    try {
      for (let offset = 0; offset < file.size; offset += CHUNK_SIZE) {
        const slice = file.slice(offset, offset + CHUNK_SIZE);
        const chunk = await encode(slice);
        const next = await request({ id, name: file.name, size: file.size, offset, chunk });
        setState(next);
        setProgress(Math.round(100 * (offset + slice.size) / file.size));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setSending(false);
    }
  };

  const reset = async () => {
    try {
      setState(await request({ reset: true }));
      lastResult.current = undefined;
      onResult(null);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not close the upload scenario.");
    }
  };

  const ingested = state.result?.files.filter((file) => file.status === "ingested").length ?? 0;
  const forecastChanges = state.result?.dashboard.readiness.flatMap((edition) => {
    const before = state.result?.before.find((row) => row.edition === edition.edition)?.p50;
    if (before == null || before === edition.p50) return [];
    const label = edition.edition === "CE" ? "Collector’s" : "Standard";
    return [`${label} ${before.toLocaleString()} → ${edition.p50.toLocaleString()}`];
  }) ?? [];
  if (hostedReplayBuild && state.status === "unavailable") return null;
  return <section className="notice upload-data" aria-label="Upload case data">
    <div>
      <strong>Upload case data</strong>
      <p className="muted">Choose one file or a ZIP up to 64 MB. The uploaded data runs in a dry-run forecast.</p>
      <div role="status">
        {sending ? `Uploading ${progress}%…` : state.status === "processing" ? `Processing ${state.name}…` :
          state.status === "ready" ? `${ingested} imported · ${(state.result?.files.length ?? 0) - ingested} unchanged · Forecast recalculated` :
          state.status === "unavailable" ? "Upload processing is unavailable." : ""}
        {state.status === "ready" && forecastChanges.length > 0 && <div>{forecastChanges.join(" · ")}</div>}
      </div>
      {(error || state.error) && <p role="alert">{error || state.error}</p>}
      {state.status === "ready" && state.result && <details>
        <summary>Files processed</summary>
        <ul>{state.result.files.map((file) => <li key={file.name}>{file.name} · {file.status}</li>)}</ul>
      </details>}
    </div>
    <div className="actions">
      <input ref={picker} type="file" accept={ACCEPT} hidden onChange={(event) => {
        const file = event.currentTarget.files?.[0];
        event.currentTarget.value = "";
        if (file) void upload(file);
      }}/>
      <button type="button" className="primary-button small" disabled={sending || state.status === "processing" || state.status === "unavailable"} onClick={() => picker.current?.click()}>Choose file or ZIP</button>
      {lastResult.current && <button type="button" className="ghost-button small" disabled={sending || state.status === "processing"} onClick={() => void reset()}>Return to launch dashboard</button>}
    </div>
  </section>;
}
