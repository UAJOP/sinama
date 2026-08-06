# SINAMA Frontend

Next.js App Router interface for the Demo Agent Playground.

## Run locally

Start the FastAPI backend on port `8000`, then:

```powershell
Copy-Item .env.example .env.local
pnpm install
pnpm dev
```

Open `http://localhost:3000`.

`NEXT_PUBLIC_API_BASE_URL` is the only frontend setting. It is public by design and defaults to `http://localhost:8000`; do not place tokens or credentials in any `NEXT_PUBLIC_*` variable.

## Quality

```powershell
pnpm lint
pnpm typecheck
pnpm build
```

The mode control starts a new isolated backend conversation. Reset clears transcript, trace and claim state while retaining the selected mode.
