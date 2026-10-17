import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router";

import { createJob, jobsAvailable } from "../api";
import { useAuth } from "../auth";
import PiiNotice, { hasPii } from "../components/PiiNotice";
import { Button, ErrorText } from "../components/ui";

const EXAMPLE =
  "Every month I get a folder of vendor bills as PDFs. I want one Excel sheet listing vendor " +
  "name, bill number, date and amount from each bill.";
const MIN_LENGTH = 10;

export default function CustomPage() {
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
    <div className="max-w-2xl">
      <h1 className="text-3xl font-bold tracking-tight">Describe your automation</h1>
      <p className="mt-3 text-slate-600">
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
          className="mt-1.5 block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm placeholder:text-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
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
              className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500"
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
  );
}
