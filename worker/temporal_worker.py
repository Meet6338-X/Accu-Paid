"""Temporal worker — runs the ingest pipeline with retries + heartbeats.

Same-machine deployment (matches workflows/core.stage_file)::

    temporal server start-dev            # dev server on localhost:7233
    python worker/temporal_worker.py     # this worker

Multi-node: point ACCUPAID_STAGING at shared storage and set TEMPORAL_HOST /
TEMPORAL_NAMESPACE (+ Temporal Cloud API key env) before starting.
The API never requires the worker: unreachable server -> inline fallback.
"""

from __future__ import annotations

import asyncio
import os


async def main() -> None:
    from temporalio.client import Client
    from temporalio.worker import Worker

    from workflows import activities
    from workflows.ingest import IngestFileWorkflow

    client = await Client.connect(os.getenv("TEMPORAL_HOST", "localhost:7233"),
                                  namespace=os.getenv("TEMPORAL_NAMESPACE", "default"))
    worker = Worker(client, task_queue=os.getenv("TEMPORAL_TASK_QUEUE", "accupaid-ingest"),
                    workflows=[IngestFileWorkflow],
                    activities=[activities.parse_file_act, activities.map_act,
                                activities.load_act])
    print("temporal worker up: accupaid-ingest", flush=True)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
