import type { ReactNode } from "react";
import { Link, useLocation } from "react-router";

import { jobsAvailable } from "../api";
import { useAuth } from "../auth";
import { Card, Spinner } from "./ui";

/** Custom jobs need the API and a login; explain what's missing instead of failing later. */
export default function RequireLogin({ children }: { children: ReactNode }) {
  const { session, loading, mode } = useAuth();
  const location = useLocation();

  if (!jobsAvailable() || mode === "none") {
    return (
      <Card>
        <p className="text-slate-700">Custom builds open soon.</p>
      </Card>
    );
  }
  if (loading) return <Spinner label="Checking your login…" />;
  if (!session) {
    return (
      <Card>
        <p className="text-slate-700">Sign in to make and follow custom automations.</p>
        <Link
          to={`/login?next=${encodeURIComponent(location.pathname)}`}
          className="mt-3 inline-block rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500"
        >
          Sign in
        </Link>
      </Card>
    );
  }
  return <>{children}</>;
}
