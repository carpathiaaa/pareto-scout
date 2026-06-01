# Pareto Scout — Web (Review Desk)

Next.js (App Router, TypeScript) review queue for the agent system. This first slice
is **read-only**: it displays scored/drafted candidates from the `agency` schema and
updates live via Supabase realtime. Approve/skip and Resend sending come next.

## Aesthetic

"Intelligence desk" — dark ink console with an amber signal accent and a teal
secondary, editorial Fraunces headers over IBM Plex Mono data. Score is rendered as a
typographic gauge; job seekers show a reachability tier chip instead.

## Structure

```
web/
├── app/
│   ├── layout.tsx      # fonts + root layout
│   ├── page.tsx        # server shell, renders <Queue>
│   └── globals.css     # the whole theme
├── components/
│   ├── Queue.tsx       # client: tabs, data load, realtime subscription
│   └── Card.tsx        # ScoredCard (leads/experts) + SeekerCard (jobs)
└── lib/
    ├── supabase.ts     # anon client, pinned to the agency schema
    ├── types.ts        # row shapes
    └── format.ts       # score/tier color + label helpers
```

## Setup

1. **Migration 003** must be applied in Supabase (RLS read policies + realtime). The
   browser anon key is otherwise locked out of `agency`. See
   `db/migrations/003_rls_read_policies.sql`.

2. **Env:** copy `.env.local.example` to `web/.env.local` and fill in:
   ```
   NEXT_PUBLIC_SUPABASE_URL=...          # same project as the agents
   NEXT_PUBLIC_SUPABASE_ANON_KEY=...     # the ANON key (NOT service-role)
   ```

3. **Install + run:**
   ```bash
   cd web
   npm install
   npm run dev
   ```
   Open http://localhost:3000.

## Notes

- The anon key is browser-exposed by design; RLS scopes it to `SELECT` only on the
  three dataset tables. `outreach_log` stays closed.
- The jobs channel may be empty even with data: only tier-1 seekers are actionable,
  and portfolio platforms rarely expose a public email. Lower tiers are stored but
  shown as "discovered, not reachable."
