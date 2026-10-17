import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from api.app import create_app
from api.config import Settings
from api.dispatch import FakeDispatcher
from api.providers.fake import FakeProvider
from api.security import callback_token, sign_body
from tests.conftest import AUTOMATIONS_DIR, INVOICE_SPEC

CALLBACK_SECRET = "test-callback-secret"
BUILD_SECRET = "test-build-secret"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
ALICE = {"Authorization": "Bearer dev:alice"}
BOB = {"Authorization": "Bearer dev:bob"}


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


@dataclass
class Ctx:
    client: AsyncClient
    provider: FakeProvider
    dispatcher: FakeDispatcher
    clock: FakeClock
    app: object

    @property
    def jobs(self):
        return self.app.state.jobs

    def session(self):
        return self.app.state.db.sessions()

    async def create_job(self, description="Make invoices from customer and item details"):
        r = await self.client.post("/jobs", json={"description": description}, headers=ALICE)
        assert r.status_code == 202, r.text
        return r.json()["job_id"]

    async def get_job(self, job_id, headers=ALICE):
        r = await self.client.get(f"/jobs/{job_id}", headers=headers)
        assert r.status_code == 200, r.text
        return r.json()

    async def routine_callback(self, job_id, token=None, **payload):
        token = token or callback_token(CALLBACK_SECRET, job_id)
        return await self.client.post(
            "/internal/routine-callback",
            json={"job_id": job_id, **payload},
            headers={"Authorization": f"Bearer {token}"},
        )

    async def build_callback(self, signature=None, **payload):
        body = json.dumps(payload).encode()
        return await self.client.post(
            "/internal/build-callback",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Signature": signature or sign_body(BUILD_SECRET, body),
            },
        )

    async def spec_ready(self, job_id, revision=0, **extra):
        r = await self.routine_callback(
            job_id,
            mode="spec",
            revision=revision,
            status="ok",
            spec=invoice_spec(),
            assumptions=["GST is 18% unless changed"],
            questions=["Do you need a discount column?"],
            **extra,
        )
        assert r.status_code == 204, r.text

    async def generated(self, job_id, attempt=0, mode="build"):
        r = await self.routine_callback(
            job_id,
            mode=mode,
            attempt=attempt,
            status="ok",
            branch=f"claude/job-{job_id}",
            commit_sha=COMMIT,
            used_custom_step=False,
        )
        assert r.status_code == 204, r.text

    async def to_building(self, job_id):
        await self.spec_ready(job_id)
        assert (await self.client.post(f"/jobs/{job_id}/confirm", headers=ALICE)).status_code == 202
        await self.generated(job_id)


def invoice_spec() -> dict:
    return json.loads(INVOICE_SPEC.read_text(encoding="utf-8"))


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        public_base_url="https://api.test",
        catalog_dir=AUTOMATIONS_DIR,
        dev_auth=True,
        watchdog_interval_s=0,
        callback_token_secret=CALLBACK_SECRET,
        build_callback_secret=BUILD_SECRET,
    )


@pytest.fixture
async def ctx(settings):
    provider, dispatcher, clock = FakeProvider(), FakeDispatcher(), FakeClock()
    app = create_app(settings, provider, dispatcher)
    app.state.jobs.clock = clock
    await app.state.db.create_all()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield Ctx(client, provider, dispatcher, clock, app)
    await app.state.db.dispose()
