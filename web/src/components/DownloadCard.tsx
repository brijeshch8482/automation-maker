import { useEffect, useRef, useState } from "react";

import { getDownload, type DownloadInfo } from "../api";
import { buttonClass, Spinner } from "./ui";
import { Check, Download, FileText, Windows } from "./icons";

const SLOW_MS = 6000; // a sleeping free-tier API takes up to a minute to wake
const REFRESH_MARGIN_S = 60; // links are signed for a few minutes; renew them shortly before

/** Starts the browser download; a seam so tests can watch it. */
export const browser = { open: (url: string) => window.location.assign(url) };

type State =
  | { status: "loading" }
  | { status: "ready"; info: DownloadInfo; fetchedAt: number }
  | { status: "unavailable" }
  | { status: "error" };

export function formatSize(bytes: number | null | undefined): string | null {
  if (!bytes) return null;
  return bytes >= 1_000_000 ? `${Math.round(bytes / 1_000_000)} MB` : `${Math.max(1, Math.round(bytes / 1000))} KB`;
}

/** Download button for a ready-made automation, with what to do after the click. */
export default function DownloadCard({ automationId }: { automationId: string }) {
  const [state, setState] = useState<State>({ status: "loading" });
  const [slow, setSlow] = useState(false);
  const [started, setStarted] = useState(false);
  const attempt = useRef(0);

  const load = async () => {
    const run = ++attempt.current;
    setState({ status: "loading" });
    setSlow(false);
    const timer = setTimeout(() => run === attempt.current && setSlow(true), SLOW_MS);
    try {
      const info = await getDownload(automationId);
      if (run !== attempt.current) return null;
      setState(info ? { status: "ready", info, fetchedAt: Date.now() } : { status: "unavailable" });
      return info;
    } catch {
      if (run === attempt.current) setState({ status: "error" });
      return null;
    } finally {
      clearTimeout(timer);
    }
  };

  useEffect(() => {
    void load();
    return () => {
      attempt.current++;
    };
  }, [automationId]); // load() reads only automationId

  const start = async () => {
    if (state.status !== "ready") return;
    let info: DownloadInfo | null = state.info;
    const ageS = (Date.now() - state.fetchedAt) / 1000;
    if (ageS > info.expires_in - REFRESH_MARGIN_S) info = await load();
    if (!info) return;
    browser.open(info.url);
    setStarted(true);
  };

  const size = state.status === "ready" ? formatSize(state.info.size_bytes) : null;

  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 p-6">
      {state.status === "ready" ? (
        <button type="button" onClick={() => void start()} className={buttonClass("primary", "lg", "w-full")}>
          <Download className="h-5 w-5" /> Download for Windows
        </button>
      ) : (
        <button type="button" disabled className={buttonClass("primary", "lg", "w-full")}>
          <Download className="h-5 w-5" /> Download for Windows
        </button>
      )}

      <div className="mt-3 text-center text-sm text-slate-600" aria-live="polite">
        {state.status === "loading" && (
          <span className="inline-flex flex-col items-center gap-1">
            <Spinner label="Checking the download…" />
            {slow && <span className="text-xs text-slate-500">Waking up our server. The first visit can take up to a minute.</span>}
          </span>
        )}
        {state.status === "ready" && (
          <span>
            {[size, `version ${state.info.version}`].filter(Boolean).join(" · ")}
          </span>
        )}
        {state.status === "unavailable" && (
          <span>Downloads open soon. The app and its guide are built and tested on Windows.</span>
        )}
        {state.status === "error" && (
          <span>
            Couldn't reach our server.{" "}
            <button type="button" onClick={() => void load()} className="font-semibold text-brand-700 hover:underline">
              Try again
            </button>
          </span>
        )}
      </div>

      {started && state.status === "ready" && (
        <AfterDownload filename={state.info.filename} guideUrl={state.info.guide_url} onRetry={() => void start()} />
      )}

      <ul className="mt-5 grid gap-2 border-t border-slate-200 pt-5 text-sm text-slate-600">
        <li className="flex items-center gap-2">
          <Windows className="h-4 w-4 text-slate-400" /> Windows 10 or 11, 64-bit
        </li>
        <li className="flex items-center gap-2">
          <Check className="h-4 w-4 text-slate-400" /> No installation, no administrator rights
        </li>
        <li className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-slate-400" />
          {state.status === "ready" ? (
            <a href={state.info.guide_url} target="_blank" rel="noreferrer" className="font-medium text-brand-700 hover:underline">
              Read the step-by-step guide (PDF)
            </a>
          ) : (
            "Guide.pdf with screenshots included"
          )}
        </li>
      </ul>
    </div>
  );
}

/** What to do once the zip is on the PC; shared with finished custom apps. */
export function AfterDownload({
  filename,
  guideUrl,
  onRetry,
}: {
  filename: string;
  guideUrl: string | null;
  onRetry?: () => void;
}) {
  const exe = filename.replace(/\.zip$/i, "") + ".exe";
  return (
    <div role="status" className="mt-5 rounded-xl border border-emerald-200 bg-emerald-50 p-5 text-sm text-emerald-950">
      <p className="font-semibold">Your download has started</p>
      <ol className="mt-3 list-decimal space-y-1.5 pl-5 leading-6">
        <li>
          Open your Downloads folder, right-click <strong>{filename}</strong> and choose <strong>Extract All</strong>.
        </li>
        <li>
          In the new folder, double-click <strong>{exe}</strong>.
        </li>
        <li>
          If Windows says “Windows protected your PC”, click <strong>More info</strong>, then <strong>Run anyway</strong>.
        </li>
      </ol>
      <p className="mt-3 text-emerald-900">
        {guideUrl && (
          <>
            <a href={guideUrl} target="_blank" rel="noreferrer" className="font-semibold underline">
              Open the guide
            </a>
            {onRetry ? " · " : ""}
          </>
        )}
        {onRetry && (
          <button type="button" onClick={onRetry} className="font-semibold underline">
            Download didn't start? Try again
          </button>
        )}
      </p>
    </div>
  );
}
