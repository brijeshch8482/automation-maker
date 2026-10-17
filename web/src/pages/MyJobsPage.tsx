import { Link } from "react-router";

import { listMyJobs } from "../api";
import RequireLogin from "../components/RequireLogin";
import StateBadge from "../components/StateBadge";
import { ErrorText, Spinner } from "../components/ui";
import { formatDate } from "../lib/jobs";
import { useAsync } from "../lib/useAsync";

export default function MyJobsPage() {
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">My automations</h1>
        <Link
          to="/custom"
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500"
        >
          New custom automation
        </Link>
      </div>
      <div className="mt-6">
        <RequireLogin>
          <JobList />
        </RequireLogin>
      </div>
    </div>
  );
}

function JobList() {
  const state = useAsync(listMyJobs, []);
  if (state.status === "loading") return <Spinner label="Loading…" />;
  if (state.status === "error") return <ErrorText error={state.error} />;
  if (state.data.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-slate-300 bg-white p-6 text-center text-slate-600">
        No custom automations yet. Describe a task and we'll design one for you.
      </p>
    );
  }
  return (
    <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
      {state.data.map((job) => (
        <li key={job.id}>
          <Link
            to={`/jobs/${job.id}`}
            className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 hover:bg-slate-50"
          >
            <span className="min-w-0">
              <span className="block truncate font-medium text-slate-900">
                {job.title ?? "Untitled automation"}
              </span>
              <span className="text-sm text-slate-500">Updated {formatDate(job.updated_at)}</span>
            </span>
            <StateBadge state={job.state} />
          </Link>
        </li>
      ))}
    </ul>
  );
}
