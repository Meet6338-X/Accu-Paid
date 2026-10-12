"""Temporal durable ingest — workflow + activities + worker service.

Same pipeline, two runtimes: Temporal server when reachable (retries,
heartbeats, cancel, live progress queries), identical inline fallback
otherwise. Content-addressed jobs (job_id = sha256(file)[:12]) dedupe
re-uploads everywhere.
"""
