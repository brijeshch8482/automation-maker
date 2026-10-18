import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";

import { getBundle, getDownload, type DownloadInfo } from "../api";
import { buttonClass, Spinner } from "./ui";
import { Check, Download, FileText, Windows } from "./icons";

const SLOW_MS = 6000; // a sleeping free-tier API takes up to a minute to wake
const REFRESH_MARGIN_S = 60; // links are signed for a few minutes; renew them shortly before

/** Starts the browser download; a seam so tests can watch it. */
export const browser = { open: (url: string) => window.location.assign(url) };

/** zip: the standalone app (internal testing); bundle: "Add to MakeMyEXE" for the installed app. */
type Links = { zip: DownloadInfo | null; bundle: DownloadInfo | null };

type State =
  | { status: "loading" }
  | { status: "ready"; links: Links; fetchedAt: number }
  | { status: "unavailable" }
  | { status: "error" };

type Kind = keyof Links;

export function formatSize(bytes: number | null | undefined): string | null {
  if (!bytes) return null;
  return bytes >= 1_000_000 ? `${Math.round(bytes / 1_000_000)} MB` : `${Math.max(1, Math.round(bytes / 1000))} KB`;
}

/**
 * Download card for a ready-made automation, with what to do after the click. Once bundles are
 * published, the main button is "Add to MakeMyEXE" (a .mmx for the installed app); the
 * standalone zip stays as a small link while the app is in internal testing.
 */
export default function DownloadCard({ automationId }: { automationId: string }) {
  const [state, setState] = useState<State>({ status: "loading" });
  const [slow, setSlow] = useState(false);
  const [started, setStarted] = useState<Kind | null>(null);
  const attempt = useRef(0);

  const load = async (): Promise<Links | null> => {
    const run = ++attempt.current;
    setState({ status: "loading" });
    setSlow(false);
    const timer = setTimeout(() => run === attempt.current && setSlow(true), SLOW_MS);
    try {
      const [zip, bundle] = await Promise.all([getDownload(automationId), getBundle(automationId)]);
      if (run !== attempt.current) return null;
      const links = { zip, bundle };
      setState(zip || bundle ? { status: "ready", links, fetchedAt: Date.now() } : { status: "unavailable" });
      return links;
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

  const start = async (kind: Kind) => {
    if (state.status !== "ready") return;
    let info = state.links[kind];
    if (!info) return;
    const ageS = (Date.now() - state.fetchedAt) / 1000;
    if (ageS > info.expires_in - REFRESH_MARGIN_S) info = (await load())?.[kind] ?? null;
    if (!info) return;
    browser.open(info.url);
    setStarted(kind);
  };

  const links = state.status === "ready" ? state.links : null;
  const main: Kind = links?.bundle ? "bundle" : "zip";
  const info = links?.[main] ?? null;
  const size = info ? formatSize(info.size_bytes) : null;
  const guideUrl = links ? (links.bundle ?? links.zip)!.guide_url : null;

  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 p-6">
      <button
        type="button"
        disabled={!info}
        onClick={() => void start(main)}
        className={buttonClass("primary", "lg", "w-full")}
      >
        <Download className="h-5 w-5" /> {main === "bundle" ? "Add to MakeMyEXE" : "Download for Windows"}
      </button>

      <div className="mt-3 text-center text-sm text-slate-600" aria-live="polite">
        {state.status === "loading" && (
          <span className="inline-flex flex-col items-center gap-1">
            <Spinner label="Checking the download…" />
            {slow && <span className="text-xs text-slate-500">Waking up our server. The first visit can take up to a minute.</span>}
          </span>
        )}
        {info && <span>{[size, `version ${info.version}`].filter(Boolean).join(" · ")}</span>}
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

      {main === "bundle" && links && (
        <p className="mt-2 text-center text-sm text-slate-600">
          Opens in the MakeMyEXE app.{" "}
          <Link to="/download" className="font-semibold text-brand-700 hover:underline">
            Get MakeMyEXE
          </Link>
          {links.zip && (
            <>
              <br />
              <button type="button" onClick={() => void start("zip")} className="mt-1 text-xs text-slate-500 underline hover:text-slate-700">
                Or download the standalone app ({formatSize(links.zip.size_bytes) ?? "zip"})
              </button>
            </>
          )}
        </p>
      )}

      {started === "bundle" && links?.bundle && (
        <AfterAdd filename={links.bundle.filename} onRetry={() => void start("bundle")} />
      )}
      {started === "zip" && links?.zip && (
        <AfterDownload filename={links.zip.filename} guideUrl={links.zip.guide_url} onRetry={() => void start("zip")} />
      )}

      <ul className="mt-5 grid gap-2 border-t border-slate-200 pt-5 text-sm text-slate-600">
        <li className="flex items-center gap-2">
          <Windows className="h-4 w-4 text-slate-400" /> Windows 10 or 11, 64-bit
        </li>
        <li className="flex items-center gap-2">
          <Check className="h-4 w-4 text-slate-400" /> No administrator rights needed
        </li>
        <li className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-slate-400" />
          {guideUrl ? (
            <a href={guideUrl} target="_blank" rel="noreferrer" className="font-medium text-brand-700 hover:underline">
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

/** What to do once a .mmx bundle is on the PC. */
export function AfterAdd({ filename, onRetry }: { filename: string; onRetry?: () => void }) {
  return (
    <div role="status" className="mt-5 rounded-xl border border-emerald-200 bg-emerald-50 p-5 text-sm text-emerald-950">
      <p className="font-semibold">Your download has started</p>
      <ol className="mt-3 list-decimal space-y-1.5 pl-5 leading-6">
        <li>
          Open <strong>{filename}</strong> from your Downloads. MakeMyEXE asks whether to add it: click <strong>Add</strong>.
        </li>
        <li>It appears in MakeMyEXE and in the Start menu. Click it to start.</li>
        <li>
          No MakeMyEXE yet?{" "}
          <Link to="/download" className="font-semibold underline">
            Install it first
          </Link>
          , then open the file again.
        </li>
      </ol>
      {onRetry && (
        <p className="mt-3">
          <button type="button" onClick={onRetry} className="font-semibold underline">
            Download didn't start? Try again
          </button>
        </p>
      )}
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
