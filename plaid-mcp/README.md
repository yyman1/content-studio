# plaid-mcp

MCP server that wraps your Plaid-connected bank accounts and exposes them as tools Claude can call.

## Tools exposed

| Tool | Description |
|---|---|
| `get_balances` | Current balances across all linked accounts |
| `get_accounts` | Account list with type/subtype/institution |
| `get_transactions` | Recent transactions (default 30 days, up to 730) |
| `get_spending_by_category` | Spending totals grouped by category |
| `search_transactions` | Search by merchant name or keyword |

## Setup

### 1. Install deps
```bash
cd plaid-mcp
npm install
```

### 2. Configure env
```bash
cp .env.example .env
# fill in PLAID_CLIENT_ID, PLAID_SECRET, PLAID_ACCESS_TOKENS
```

`PLAID_ACCESS_TOKENS` is a comma-separated list of `access_token` values — one per institution you've linked via Plaid Link. You only run Link once per bank; tokens are long-lived.

### 3. Run it

**Dev mode:**
```bash
npm run dev
```

**Production (after `npm run build`):**
```bash
npm start
```

---

## Connect to Claude Desktop (local)

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "plaid": {
      "command": "node",
      "args": ["/absolute/path/to/plaid-mcp/dist/server.js"],
      "env": {
        "PLAID_CLIENT_ID": "...",
        "PLAID_SECRET": "...",
        "PLAID_ENV": "production",
        "PLAID_ACCESS_TOKENS": "access-production-...",
        "MCP_TRANSPORT": "stdio"
      }
    }
  }
}
```

Restart Claude Desktop. You'll see a hammer icon — your tools are live.

---

## Deploy to DigitalOcean (remote / Claude.ai)

```bash
# On your droplet
git pull
cd plaid-mcp
npm install && npm run build

# Run with pm2 so it stays up
npm install -g pm2
MCP_TRANSPORT=http PORT=3100 pm2 start dist/server.js --name plaid-mcp
pm2 save
```

Then add a Caddy or nginx reverse-proxy block for HTTPS:

```
# Caddyfile snippet
plaid-mcp.yourdomain.com {
    reverse_proxy localhost:3100
}
```

In Claude.ai → Settings → Integrations → Add MCP server:
- URL: `https://plaid-mcp.yourdomain.com/mcp`

---

## Example conversations

- *"What's my current cash position across all accounts?"*
- *"How much did I spend on restaurants last month?"*
- *"Show me all transactions over $200 in the past two weeks."*
- *"Compare my food spending this month vs last month."*
- *"Search my transactions for Costco."*
