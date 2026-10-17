import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router";

import { createJob, jobsAvailable } from "../api";
import { useAuth } from "../auth";
import PiiNotice, { hasPii } from "../components/PiiNotice";
import { Button, buttonClass, ErrorText, Eyebrow, usePageMeta } from "../components/ui";

const EXAMPLE =
  "Every month I get a folder of vendor bills as PDFs. I want one Excel sheet listing vendor " +
  "name, bill number, date and amount from each bill.";
const MIN_LENGTH = 10;

export default function CustomPage() {
  usePageMeta(
    "Request a custom app",
    "Describe a task you do by hand and get a Windows app for it that runs offline on your PC.",
  );
  const location = useLocation();
  const navigate = useNavigate();
  const { session, mode } = useAuth();
  const prefill = (location.state as { description?: string } | null)?.description ?? "";
  const [description, setDescription] = useState(prefill);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const available = jobsAvailable() && mode !== "none";
  const blocked = hasPii(description);
  const tooShort = description.trim().length < MIN_LENGTH;

  const submit = async () => {
    setSending(true);
    setError(null);
    try {
      const id = await createJob(description.trim());
      navigate(`/jobs/${id}`);
    } catch (err) {
      setError(err);
      setSending(false);
    }
  };

  return (
    <div className="grid gap-12 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
      <div>
        <Eyebrow>Custom app</Eyebrow>
        <h1 className="mt-3 text-4xl font-bold tracking-tight">Describe your automation</h1>
        <p className="mt-4 text-lg leading-8 text-slate-600">
          Tell us what you do by hand today. We only need the <em>format</em> of the task: what
          goes in, what should come out. Don't include real names, numbers or files. You'll enter
          your real data inside the app, on your own PC.
        </p>

        <form
          className="mt-6"
          onSubmit={(e) => {
            e.preventDefault();
            if (available && session && !blocked && !tooShort && !sending) void submit();
          }}
        >
          <label htmlFor="description" className="block text-sm font-medium text-slate-800">
            What should it do?
          </label>
          <textarea
            id="description"
            rows={7}
            maxLength={4000}
            className="mt-1.5 block w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm leading-6 shadow-sm placeholder:text-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
            placeholder={EXAMPLE}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            aria-describedby={blocked ? "pii-warning" : undefined}
          />
          <PiiNotice id="pii-warning" text={description} onMask={setDescription} />

          <div className="mt-5 flex flex-wrap items-center gap-3">
            {available && !session ? (
              <Link
                to="/login?next=/custom"
                state={{ description }}
                className={buttonClass()}
              >
                Sign in to continue
              </Link>
            ) : (
              <Button type="submit" disabled={!available || blocked || tooShort || sending}>
                {sending ? "Sending…" : "Design my automation"}
              </Button>
            )}
            {!available && <p className="text-sm text-slate-500">Custom builds open soon.</p>}
            {available && blocked && (
              <p className="text-sm text-amber-800">Mask the highlighted details to continue.</p>
            )}
          </div>
          <ErrorText error={error} />
        </form>
      </div>
      <NextSteps />
    </div>
  );
}

const NEXT_STEPS: [string, string][] = [
  ["We design it", "In a few minutes you see the app's form and steps, plus anything we assumed."],
  ["You check it", "Change fields, answer our questions, or ask for a new version. Nothing is built yet."],
  ["We build and test it", "When you confirm, the app is built on Windows and tested with sample data."],
  ["You download it", "It appears under My apps, with a step-by-step Guide.pdf."],
];

function NextSteps() {
  return (
    <aside className="h-fit rounded-2xl border border-slate-200 bg-slate-50 p-7">
      <h2 className="text-base font-semibold text-slate-900">What happens next</h2>
      <ol className="mt-5 space-y-5">
        {NEXT_STEPS.map(([title, text], i) => (
          <li key={title} className="flex gap-4">
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-600 text-sm font-semibold text-white">
              {i + 1}
            </span>
            <div>
              <p className="text-sm font-semibold text-slate-900">{title}</p>
              <p className="mt-0.5 text-sm leading-6 text-slate-600">{text}</p>
            </div>
          </li>
        ))}
      </ol>
      <div className="mt-6 border-t border-slate-200 pt-5 text-sm leading-6 text-slate-600">
        <p className="font-semibold text-slate-900">Tips for a good description</p>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          <li>What you start with: a form to fill, a folder of files, a spreadsheet.</li>
          <li>What should come out: a PDF, renamed files, a new sheet.</li>
          <li>Any rule you follow, like numbering or how totals are worked out.</li>
        </ul>
      </div>
    </aside>
  );
}
