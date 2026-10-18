import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";

import { getLatestApp, type AppDownloadInfo } from "../api";
import { browser, formatSize } from "../components/DownloadCard";
import { Check, Download, Shield, WifiOff, Windows } from "../components/icons";
import { buttonClass, Eyebrow, Spinner, usePageMeta } from "../components/ui";

type State =
  | { status: "loading" }
  | { status: "ready"; info: AppDownloadInfo; fetchedAt: number }
  | { status: "unavailable" }
  | { status: "error" };

const REFRESH_MARGIN_S = 60;

/** "Download MakeMyEXE": the installer, what it needs, and what happens next (DESKTOP_APP.md §2.1). */
export default function DownloadPage() {
  usePageMeta("Download MakeMyEXE", "Install MakeMyEXE once, then add automations to it. Windows 10 and 11, no administrator rights.");
  const [state, setState] = useState<State>({ status: "loading" });
  const [started, setStarted] = useState(false);
  const attempt = useRef(0);

  const load = async () => {
    const run = ++attempt.current;
    setState({ status: "loading" });
    try {
      const info = await getLatestApp();
      if (run !== attempt.current) return null;
      setState(info ? { status: "ready", info, fetchedAt: Date.now() } : { status: "unavailable" });
      return info;
    } catch {
      if (run === attempt.current) setState({ status: "error" });
      return null;
    }
  };

  useEffect(() => {
    void load();
    return () => {
      attempt.current++;
    };
  }, []);

  const start = async () => {
    if (state.status !== "ready") return;
    let info: AppDownloadInfo | null = state.info;
    if ((Date.now() - state.fetchedAt) / 1000 > info.expires_in - REFRESH_MARGIN_S) info = await load();
    if (!info) return;
    browser.open(info.url);
    setStarted(true);
  };

  const info = state.status === "ready" ? state.info : null;

  return (
    <div className="mx-auto max-w-3xl">
      <Eyebrow>The app</Eyebrow>
      <h1 className="mt-2 text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">Download MakeMyEXE</h1>
      <p className="mt-4 text-lg leading-8 text-slate-600">
        Install it once. Then add automations from the website: each one opens from MakeMyEXE or the Start menu, and
        runs on your PC, offline.
      </p>

      <div className="mt-8 rounded-2xl border border-slate-200 bg-slate-50 p-6">
        <button type="button" disabled={!info} onClick={() => void start()} className={buttonClass("primary", "lg", "w-full sm:w-auto")}>
          <Download className="h-5 w-5" /> Download for Windows
        </button>
        <div className="mt-3 text-sm text-slate-600" aria-live="polite">
          {state.status === "loading" && <Spinner label="Checking the latest version…" />}
          {info && <span>{[formatSize(info.size_bytes), `version ${info.version}`].filter(Boolean).join(" · ")}</span>}
          {state.status === "unavailable" && <span>The first release is on its way. Check back soon.</span>}
          {state.status === "error" && (
            <span>
              Couldn't reach our server.{" "}
              <button type="button" onClick={() => void load()} className="font-semibold text-brand-700 hover:underline">
                Try again
              </button>
            </span>
          )}
        </div>

        {started && info && (
          <div role="status" className="mt-5 rounded-xl border border-emerald-200 bg-emerald-50 p-5 text-sm text-emerald-950">
            <p className="font-semibold">Your download has started</p>
            <ol className="mt-3 list-decimal space-y-1.5 pl-5 leading-6">
              <li>
                Open <strong>{info.filename}</strong> from your Downloads.
              </li>
              <li>
                If Windows says “Windows protected your PC”, click <strong>More info</strong>, then <strong>Run anyway</strong>.
                We're getting the app signed so this message goes away.
              </li>
              <li>
                Click <strong>Install</strong>. MakeMyEXE opens with four free automations ready to use.
              </li>
            </ol>
            <p className="mt-3">
              <button type="button" onClick={() => void start()} className="font-semibold underline">
                Download didn't start? Try again
              </button>
            </p>
          </div>
        )}

        <ul className="mt-5 grid gap-2 border-t border-slate-200 pt-5 text-sm text-slate-600 sm:grid-cols-2">
          <li className="flex items-center gap-2">
            <Windows className="h-4 w-4 text-slate-400" /> Windows 10 or 11, 64-bit
          </li>
          <li className="flex items-center gap-2">
            <Check className="h-4 w-4 text-slate-400" /> Installs for you only, no administrator rights
          </li>
          <li className="flex items-center gap-2">
            <WifiOff className="h-4 w-4 text-slate-400" /> The app itself never goes online
          </li>
          <li className="flex items-center gap-2">
            <Shield className="h-4 w-4 text-slate-400" /> Runs only automations signed by us
          </li>
        </ul>
      </div>

      <h2 className="mt-12 text-xl font-semibold text-slate-900">Then add automations</h2>
      <ol className="mt-4 list-decimal space-y-2 pl-5 leading-7 text-slate-700">
        <li>
          Pick one in the <Link to="/automations" className="font-semibold text-brand-700 hover:underline">catalog</Link>, or{" "}
          <Link to="/custom" className="font-semibold text-brand-700 hover:underline">describe your own</Link>.
        </li>
        <li>
          Press <strong>Add to MakeMyEXE</strong> and open the downloaded <code className="rounded bg-slate-100 px-1">.mmx</code> file.
        </li>
        <li>MakeMyEXE checks it and asks before adding it. It then shows up in the app and in the Start menu.</li>
      </ol>

      <h2 className="mt-12 text-xl font-semibold text-slate-900">Uninstalling</h2>
      <p className="mt-3 leading-7 text-slate-700">
        Settings › Apps › MakeMyEXE › Uninstall. It asks whether to keep your automations and their settings, and never
        touches the files you made with them.
      </p>
    </div>
  );
}
