import { useCallback, useEffect, useState } from "react";

import { getJob, type Job } from "../api";
import { WAITING_STATES } from "./jobs";

export const POLL_MS = 3000;

/** Load a job and keep checking it while the server is working on it. */
export function useJob(id: string) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(async () => {
    try {
      setJob(await getJob(id));
      setError(null);
    } catch (err) {
      setError(err);
    }
  }, [id]);

  useEffect(() => {
    setJob(null);
    setError(null);
    void load();
  }, [load]);

  const waiting = job !== null && WAITING_STATES.has(job.state);
  useEffect(() => {
    if (!waiting) return;
    const timer = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(timer);
  }, [waiting, load]);

  return { job, error, setJob, reload: load };
}
