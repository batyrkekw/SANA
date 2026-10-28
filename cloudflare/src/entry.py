"""Python Worker entrypoint. The local FastAPI API remains the source of truth."""

import json
import os

from workers import WorkerEntrypoint, asgi, env

# One fixed deployment configuration per isolate, before importing the shared app.
for key, value in json.loads(env.SANA_PUBLIC_CONFIG).items():
    os.environ[key] = value
os.environ.update(
    {
        "SANA_RUNTIME": "cloudflare",
        "SANA_ENVIRONMENT": "production",
        "SANA_AUTH_MODE": "auth_server",
        "SANA_LLM_MODEL": "@cf/qwen/qwen3-30b-a3b-fp8",
        "SANA_IMAGE_ENABLED": "false",
        "SANA_JOB_TIMEOUT_SECONDS": "600",
        "SANA_DAILY_GENERATION_LIMIT": "20",
    }
)

from cloud_runtime import CloudRuntime, cloud_database  # noqa: E402

from app.db import get_db  # noqa: E402
from app.main import app, config  # noqa: E402

runtime = CloudRuntime(env, config)
app.state.cloud = runtime
app.dependency_overrides[get_db] = cloud_database


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        return await asgi.fetch(app, request, self.env, self.ctx)

    async def queue(self, batch, _env=None, _ctx=None):
        for message in batch.messages:
            try:
                await runtime.generate(str(message.body["job_id"]))
                message.ack()
            except Exception:
                # No exception strings: provider/DB errors can contain credentials or prompts.
                message.retry()

    async def scheduled(self, controller, _env, _ctx):
        await runtime.dispatch_and_recover()
