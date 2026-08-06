# Backend

Target: **Python + FastAPI**.

This directory is intentionally documentation-only until the implementation scaffold is generated.

Initial backend responsibilities:

- health endpoint
- agent adapters
- scenario execution
- tool-call capture and normalization
- deterministic evaluators
- run/result API
- PostgreSQL/Supabase persistence when introduced

Start with in-process async execution. Do not add a distributed worker queue until real workload or reliability requirements justify it.
