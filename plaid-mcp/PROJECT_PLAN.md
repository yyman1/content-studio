# Plaid MCP — Project Plan

## Goal
Connect personal bank accounts (via Plaid) to Claude so you can ask natural-language questions about your finances from any device.

---

## Milestones

### M1 — Plaid credentials & sandbox validation
**Est: 1–2 hours**

- [ ] Create Plaid developer account at dashboard.plaid.com
- [ ] Note `PLAID_CLIENT_ID` and sandbox `PLAID_SECRET`
- [ ] Run Plaid Quickstart (or the minimal Link flow below) to get a sandbox `access_token`
- [ ] Copy `.env.example` → `.env`, fill in the three vars
- [ ] Smoke-test: `npm run dev` and confirm the server starts without errors

**Minimal Link flow (no frontend needed for sandbox):**
```bash
# Exchange a public_token from Plaid's sandbox test credentials
# Plaid docs: https://plaid.com/docs/quickstart/
```

---

### M2 — Local Claude Desktop integration
**Est: 1–2 hours**

- [ ] `npm run build` — compile TypeScript to `dist/`
- [ ] Add entry to `claude_desktop_config.json` (see README) pointing at `dist/server.js`
- [ ] Restart Claude Desktop
- [ ] Verify hammer icon appears and all 5 tools show up
- [ ] Test each tool manually in Claude:
  - [ ] "What accounts do I have linked?"
  - [ ] "What are my current balances?"
  - [ ] "Show me my last 30 days of transactions"
  - [ ] "What did I spend the most on this month?"
  - [ ] "Search for any Amazon transactions"

---

### M3 — Real bank connection (production)
**Est: 1–2 hours**

- [ ] Switch `PLAID_ENV=production` and use production `PLAID_SECRET`
- [ ] Run Plaid Link for each institution (checking, savings, credit cards)
  - Each Link run yields one `access_token` — collect them all
- [ ] Update `PLAID_ACCESS_TOKENS` in `.env` (comma-separated)
- [ ] Re-test all 5 tools with live data
- [ ] Confirm transaction pagination works (accounts with >500 transactions)

---

### M4 — Deploy to DigitalOcean (remote access)
**Est: 1–2 hours**

- [ ] SSH into droplet at 104.131.97.109
- [ ] Clone repo, `cd plaid-mcp`, `npm install && npm run build`
- [ ] Set env vars (export or write a `.env` on the server — never commit real tokens)
- [ ] Start with pm2: `MCP_TRANSPORT=http PORT=3100 pm2 start dist/server.js --name plaid-mcp`
- [ ] Add HTTPS via Caddy or nginx (required — Claude.ai rejects plain HTTP)
- [ ] Confirm `/mcp` endpoint responds over HTTPS
- [ ] Add to Claude.ai → Settings → Integrations → Add MCP server

---

### M5 — Hardening & quality of life
**Est: 2–4 hours, can be done incrementally**

- [ ] **Error handling** — graceful messages when Plaid returns a rate-limit or token-expired error
- [ ] **Token refresh detection** — log a clear message if an `access_token` needs re-linking
- [ ] **Multi-institution labels** — tag each transaction/balance with institution name (requires storing a `token → institution` map in `.env` or a tiny JSON file)
- [ ] **Date filtering on `get_transactions`** — add optional `start_date` / `end_date` params alongside `days`
- [ ] **Net worth snapshot tool** — sum assets minus liabilities across all accounts
- [ ] **pm2 log rotation** — `pm2 install pm2-logrotate` so the droplet doesn't fill up

---

## Risk log

| Risk | Likelihood | Mitigation |
|---|---|---|
| Plaid production approval takes time | Low — personal dev use is usually instant | Start in sandbox, switch when approved |
| `access_token` expires / item enters error state | Medium | Plaid sends webhooks; for now, just re-run Link if Claude reports an error |
| Droplet port 3100 blocked by firewall | Low | `ufw allow 3100` or route through Caddy on 443 |
| Sensitive data in Claude context window | Low | Plaid data stays server-side; only JSON summaries are sent to Claude |

---

## Nice-to-haves (post-M5)

- Budget tracking tool — compare spending vs. a monthly target per category
- Recurring charge detector — flag subscriptions from transaction history
- CSV export tool — dump transactions to a file Claude can analyze in detail
- Webhook receiver — Plaid can push new transactions in real time instead of polling

---

## Quick reference

```
Your Banks → Plaid API → plaid-mcp server → Claude (Desktop or Claude.ai)

Transport options:
  stdio  →  Claude Desktop (local only, no network exposure)
  http   →  Claude.ai via HTTPS (accessible from any device)
```
