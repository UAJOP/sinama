# External Agent Timeout

SINAMA gives each external HTTP agent turn up to **60 seconds** by default.

This budget applies both to the connection probe and to scenario execution through the normal external-agent adapter. It is intentionally long enough for real LLM-backed bots and agent workflows while remaining bounded so stalled endpoints still become explicit reliability evidence.

The deadline is configured with:

```text
SINAMA_EXTERNAL_AGENT_TIMEOUT_SECONDS=60
```

Valid values are greater than zero and at most 60 seconds. The outbound safety boundary is unchanged: production endpoints still require HTTPS, SSRF protections remain active, redirects stay disabled, proxy environment variables are ignored, and response size remains bounded.
