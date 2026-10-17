"""RoutineProvider: fires the Claude Code routines am-spec / am-build (docs/ROUTINES.md §2)."""

from __future__ import annotations

import json
from typing import Any

import httpx

from api.providers.base import FireRejected, FireUnknown, JobContext, RetryLater, RunRef

MAX_TEXT_CHARS = 65_536
DEFAULT_RETRY_AFTER_S = 60


class RoutineProvider:
    def __init__(
        self,
        *,
        spec_url: str,
        spec_token: str,
        build_url: str,
        build_token: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._spec = (spec_url, spec_token)
        self._build = (build_url, build_token)
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))

    async def request_spec(
        self,
        job: JobContext,
        description: str,
        answers: list[dict[str, str]],
        previous_spec: dict[str, Any] | None,
    ) -> RunRef:
        payload = {
            "v": 1,
            "mode": "spec",
            "job_id": job.job_id,
            "revision": job.revision,
            "callback_url": job.callback_url,
            "callback_token": job.callback_token,
            "description": description,
            "previous_spec": previous_spec,
            "answers": answers,
        }
        return await self._fire(self._spec, payload)

    async def request_build(self, job: JobContext, spec: dict[str, Any]) -> RunRef:
        payload = {
            "v": 1,
            "mode": "build",
            "job_id": job.job_id,
            "attempt": job.attempt,
            "callback_url": job.callback_url,
            "callback_token": job.callback_token,
            "spec": spec,
        }
        return await self._fire(self._build, payload)

    async def request_repair(self, job: JobContext, report: dict[str, Any]) -> RunRef:
        payload = {
            "v": 1,
            "mode": "repair",
            "job_id": job.job_id,
            "attempt": job.attempt,
            "branch": job.branch,
            "callback_url": job.callback_url,
            "callback_token": job.callback_token,
            "report": report,
        }
        return await self._fire(self._build, payload)

    async def _fire(self, target: tuple[str, str], payload: dict[str, Any]) -> RunRef:
        url, token = target
        if not url or not token:
            raise FireRejected("routine URL or token is not configured")
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(text) > MAX_TEXT_CHARS:
            raise FireRejected(f"payload is {len(text)} chars, the limit is {MAX_TEXT_CHARS}")

        try:
            response = await self._client.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={"text": text},
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as err:
            raise RetryLater(DEFAULT_RETRY_AFTER_S, f"could not connect: {err}") from err
        except httpx.HTTPError as err:
            # Sent (or partly sent) without a clear answer: a session may exist.
            raise FireUnknown(f"no response from the fire endpoint: {err!r}") from err

        if response.status_code == 429:
            raise RetryLater(_retry_after(response), "rate limited (429)")
        if response.status_code >= 500:
            raise FireUnknown(f"fire endpoint returned {response.status_code}")
        if response.status_code != 200:
            raise FireRejected(
                f"fire endpoint returned {response.status_code}: {response.text[:300]}"
            )

        try:
            body = response.json()
            return RunRef(body["claude_code_session_id"], body["claude_code_session_url"])
        except (ValueError, KeyError, TypeError) as err:
            # A 200 means a session was created even if we can't read its id.
            raise FireUnknown(f"unexpected fire response: {response.text[:300]}") from err


def _retry_after(response: httpx.Response) -> int:
    try:
        return max(1, int(response.headers.get("Retry-After", DEFAULT_RETRY_AFTER_S)))
    except ValueError:
        return DEFAULT_RETRY_AFTER_S
