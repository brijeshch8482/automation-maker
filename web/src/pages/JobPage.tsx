import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import {
  answerQuestions,
  ApiError,
  confirmJob,
  saveSpec,
  type Answer,
  type Job,
} from "../api";
import JobProgress from "../components/JobProgress";
import PiiNotice, { hasPii } from "../components/PiiNotice";
import RequireLogin from "../components/RequireLogin";
import SpecEditor from "../components/SpecEditor";
import SpecPreview from "../components/SpecPreview";
import StateBadge from "../components/StateBadge";
import { Button, Card, ErrorText, Spinner } from "../components/ui";
import { ATTEMPT_LABELS, ATTEMPT_STATUS_LABELS, formatDate } from "../lib/jobs";
import { useJob } from "../lib/useJob";
import type { AutomationSpec } from "../types/spec";
import NotFoundPage from "./NotFoundPage";

export default function JobPage() {
  return (
    <RequireLogin>
      <JobLoader />
    </RequireLogin>
  );
}

function JobLoader() {
  const { id = "" } = useParams();
  const { job, error, setJob } = useJob(id);

  if (error instanceof ApiError && error.status === 404) return <NotFoundPage what="job" />;
  if (!job) {
    return error ? <ErrorText error={error} /> : <Spinner label="Loading your automation…" />;
  }
  return <JobView job={job} onJob={setJob} stale={error} />;
}

function JobView({ job, onJob, stale }: { job: Job; onJob: (job: Job) => void; stale: unknown }) {
  return (
    <div className="space-y-6">
      <div>
        <Link to="/me/jobs" className="text-sm font-medium text-indigo-700 hover:underline">
          ← My automations
        </Link>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">
            {job.spec?.title ?? "Your custom automation"}
          </h1>
          <StateBadge state={job.state} />
        </div>
        <p className="mt-1 text-sm text-slate-500">Started {formatDate(job.created_at)}</p>
        <div className="mt-4">
          <JobProgress state={job.state} />
        </div>
        {stale ? (
          <p className="mt-2 text-sm text-amber-700">Couldn't refresh just now. Retrying…</p>
        ) : null}
      </div>

      {job.state === "spec_ready" && job.spec ? (
        <SpecReview job={job} spec={job.spec} onJob={onJob} />
      ) : (
        <StatusPanel job={job} />
      )}

      <JobDetails job={job} />
    </div>
  );
}

// --- Waiting / finished states ----------------------------------------------------------

function StatusPanel({ job }: { job: Job }) {
  const navigate = useNavigate();
  const tryAgain = () => navigate("/custom", { state: { description: job.description ?? "" } });

  switch (job.state) {
    case "draft":
    case "spec_requested":
      return (
        <Working
          title={job.revision > 0 ? "Updating the design with your answers" : "Designing your automation"}
          text="Claude is turning your description into fields and steps. This usually takes a few minutes. You can leave this page; we'll keep going."
        />
      );
    case "queued":
      return <Working title="Waiting for a free build slot" text="Your build starts in a moment." />;
    case "generating":
      return (
        <Working
          title="Generating your app"
          text="Claude is setting up the app from your design and checking it with sample data."
        />
      );
    case "building":
      return (
        <Working
          title="Building the Windows app"
          text={
            job.attempt > 0
              ? `Building again after a fix (try ${job.attempt} of 2). Then we make the step-by-step guide.`
              : "Packaging the app and making the step-by-step guide with screenshots."
          }
        />
      );
    case "repairing":
      return (
        <Working
          title="Fixing a problem found in the build"
          text={`The Windows build found a problem, and Claude is fixing it (try ${job.attempt} of 2).`}
        />
      );
    case "ready":
      return (
        <Card>
          <h2 className="text-lg font-semibold text-emerald-800">Your app is ready</h2>
          <p className="mt-1 text-slate-700">
            It runs offline on your Windows PC. Your real data is entered only inside the app.
          </p>
          <div className="mt-4">
            {job.download_url ? (
              <a
                href={job.download_url}
                className="inline-block rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500"
              >
                Download for Windows
              </a>
            ) : (
              <>
                <Button disabled>Download for Windows</Button>
                <p className="mt-2 text-sm text-slate-500">
                  The download link will appear here soon.
                </p>
              </>
            )}
          </div>
        </Card>
      );
    case "failed":
      return (
        <Card>
          <h2 className="text-lg font-semibold text-rose-800">We couldn't finish this one</h2>
          <p className="mt-1 text-slate-700">{sentence(job.failure_reason ?? "Something went wrong.")}</p>
          <Button className="mt-4" onClick={tryAgain} disabled={!job.description}>
            Try again with the same description
          </Button>
        </Card>
      );
    case "expired":
      return (
        <Card>
          <h2 className="text-lg font-semibold">This design expired</h2>
          <p className="mt-1 text-slate-700">
            Designs that aren't confirmed within 30 days are closed. You can start a new one any time.
          </p>
          <Button className="mt-4" onClick={tryAgain} disabled={!job.description}>
            Start again with the same description
          </Button>
        </Card>
      );
    default:
      return null;
  }
}

function Working({ title, text }: { title: string; text: string }) {
  return (
    <Card>
      <Spinner label={title} />
      <p className="mt-2 text-sm text-slate-600">{text}</p>
    </Card>
  );
}

// --- Spec review --------------------------------------------------------------------------

function SpecReview({ job, spec, onJob }: { job: Job; spec: AutomationSpec; onJob: (job: Job) => void }) {
  const [draft, setDraft] = useState(spec);
  const [saving, setSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [issues, setIssues] = useState<string[]>([]);

  // A new revision from the server replaces local edits.
  useEffect(() => setDraft(spec), [spec]);
  const dirty = JSON.stringify(draft) !== JSON.stringify(spec);

  const save = async () => {
    setSaving(true);
    setError(null);
    setIssues([]);
    try {
      onJob(await saveSpec(job.id, draft));
    } catch (err) {
      setError(err);
      if (err instanceof ApiError) setIssues(err.issues);
    } finally {
      setSaving(false);
    }
  };

  const confirm = async () => {
    setConfirming(true);
    setError(null);
    try {
      onJob(await confirmJob(job.id));
    } catch (err) {
      setError(err);
      setConfirming(false);
    }
  };

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] lg:items-start">
      <div className="space-y-6">
        {job.assumptions.length > 0 && (
          <Card title="What we assumed">
            <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
              {job.assumptions.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          </Card>
        )}
        {job.questions.length > 0 && <Questions job={job} onJob={onJob} />}
        <Card title="Adjust the app">
          <SpecEditor spec={draft} onChange={setDraft} />
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button onClick={save} disabled={!dirty || saving}>
              {saving ? "Saving…" : "Save changes"}
            </Button>
            {dirty && (
              <Button variant="secondary" onClick={() => setDraft(spec)}>
                Undo changes
              </Button>
            )}
          </div>
          {issues.length > 0 && (
            <div role="alert" className="mt-3 rounded-md bg-rose-50 p-3 text-sm text-rose-900">
              <p className="font-semibold">These changes can't be saved yet</p>
              <p className="mt-1">
                {issues.some((i) => i.startsWith("steps["))
                  ? "A step of the app still uses a field you removed. Undo that change, or ask for it in an answer above so we update the design."
                  : "Please check the fields you changed."}
              </p>
              <ul className="mt-2 list-disc pl-5 font-mono text-xs text-rose-800">
                {issues.map((issue) => (
                  <li key={issue}>{issue}</li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      </div>

      <div className="space-y-4 lg:sticky lg:top-6">
        <h2 className="text-sm font-semibold text-slate-700">Preview</h2>
        <SpecPreview key={`${job.revision}`} spec={draft} />
        <Card>
          <p className="text-sm text-slate-700">
            Happy with it? We'll build the Windows app and its step-by-step guide.
          </p>
          <Button className="mt-3 w-full sm:w-auto" onClick={confirm} disabled={dirty || confirming}>
            {confirming ? "Starting…" : "Build my app"}
          </Button>
          {dirty && <p className="mt-2 text-xs text-slate-500">Save your changes first.</p>}
          {issues.length === 0 && <ErrorText error={error} />}
        </Card>
      </div>
    </div>
  );
}

function Questions({ job, onJob }: { job: Job; onJob: (job: Job) => void }) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const filled: Answer[] = job.questions
    .map((question) => ({ question, answer: (answers[question] ?? "").trim() }))
    .filter((a) => a.answer);
  const blocked = filled.some((a) => hasPii(a.answer));

  const send = async () => {
    setSending(true);
    setError(null);
    try {
      onJob(await answerQuestions(job.id, filled));
    } catch (err) {
      setError(err);
      setSending(false);
    }
  };

  return (
    <Card title="A few questions">
      <p className="-mt-1 mb-3 text-sm text-slate-600">
        Answer any you like and we'll update the design. Or skip them and build as it is.
      </p>
      <div className="space-y-4">
        {job.questions.map((question, i) => {
          const id = `answer-${i}`;
          const value = answers[question] ?? "";
          return (
            <div key={question}>
              <label htmlFor={id} className="mb-1 block text-sm font-medium text-slate-800">
                {question}
              </label>
              <textarea
                id={id}
                rows={2}
                maxLength={2000}
                className="block w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
                value={value}
                onChange={(e) => setAnswers({ ...answers, [question]: e.target.value })}
              />
              <PiiNotice text={value} onMask={(masked) => setAnswers({ ...answers, [question]: masked })} />
            </div>
          );
        })}
      </div>
      <Button className="mt-4" variant="secondary" onClick={send} disabled={!filled.length || blocked || sending}>
        {sending ? "Sending…" : "Update the design"}
      </Button>
      <ErrorText error={error} />
    </Card>
  );
}

/** Server messages are lower-case fragments; show them as a sentence. */
function sentence(text: string): string {
  const trimmed = text.trim();
  const capitalized = trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
  return /[.!?]$/.test(capitalized) ? capitalized : `${capitalized}.`;
}

// --- Details --------------------------------------------------------------------------------

function JobDetails({ job }: { job: Job }) {
  return (
    <details className="rounded-lg border border-slate-200 bg-white p-4 text-sm">
      <summary className="cursor-pointer font-semibold text-slate-800">Details</summary>
      {job.description && (
        <div className="mt-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Your description</h3>
          <p className="mt-1 whitespace-pre-wrap text-slate-700">{job.description}</p>
        </div>
      )}
      {job.attempts.length > 0 && (
        <div className="mt-4">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Behind the scenes</h3>
          <ul className="mt-1 divide-y divide-slate-100">
            {job.attempts.map((a, i) => (
              <li key={i} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5">
                <span className="font-medium text-slate-800">
                  {ATTEMPT_LABELS[a.mode]}
                  {a.mode === "spec" && a.revision > 0 ? ` (update ${a.revision})` : ""}
                  {a.mode === "repair" ? ` ${a.attempt}` : ""}
                </span>
                <span className="text-slate-500">{ATTEMPT_STATUS_LABELS[a.status] ?? a.status}</span>
                <span className="text-slate-400">{formatDate(a.created_at)}</span>
                {a.session_url && (
                  <a href={a.session_url} target="_blank" rel="noreferrer" className="text-indigo-700 hover:underline">
                    View session
                  </a>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      {job.run_url && (
        <a href={job.run_url} target="_blank" rel="noreferrer" className="mt-3 inline-block text-indigo-700 hover:underline">
          View the Windows build
        </a>
      )}
    </details>
  );
}
