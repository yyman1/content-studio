import "dotenv/config";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { z } from "zod";
import { createServer } from "http";
import { fetchBalances, fetchTransactions, fetchAccounts } from "./plaid-client.js";

const server = new McpServer({
  name: "plaid-mcp",
  version: "1.0.0",
});

// ── Tool: get_balances ────────────────────────────────────────────────────────
server.tool(
  "get_balances",
  "Get current balances for all linked bank and investment accounts",
  {},
  async () => {
    const accounts = await fetchBalances();
    const summary = accounts.map((a) => ({
      name: a.name,
      mask: a.mask,
      type: a.type,
      subtype: a.subtype,
      current: a.balances.current,
      available: a.balances.available,
      currency: a.balances.iso_currency_code,
    }));
    return { content: [{ type: "text", text: JSON.stringify(summary, null, 2) }] };
  }
);

// ── Tool: get_transactions ────────────────────────────────────────────────────
server.tool(
  "get_transactions",
  "Get transactions for the past N days (default 30) across all linked accounts",
  { days: z.number().int().min(1).max(730).default(30).describe("Number of days back to fetch") },
  async ({ days }) => {
    const txns = await fetchTransactions(days);
    const summary = txns.map((t) => ({
      date: t.date,
      name: t.merchant_name ?? t.name,
      amount: t.amount,           // positive = debit, negative = credit (Plaid convention)
      category: t.personal_finance_category?.primary ?? t.category?.[0],
      account_id: t.account_id,
    }));
    return { content: [{ type: "text", text: JSON.stringify(summary, null, 2) }] };
  }
);

// ── Tool: get_spending_by_category ────────────────────────────────────────────
server.tool(
  "get_spending_by_category",
  "Summarize total spending grouped by category for the past N days",
  { days: z.number().int().min(1).max(730).default(30).describe("Number of days back") },
  async ({ days }) => {
    const txns = await fetchTransactions(days);
    const totals: Record<string, number> = {};
    for (const t of txns) {
      if (t.amount <= 0) continue; // skip credits/refunds
      const cat = t.personal_finance_category?.primary ?? t.category?.[0] ?? "OTHER";
      totals[cat] = (totals[cat] ?? 0) + t.amount;
    }
    const sorted = Object.entries(totals)
      .sort(([, a], [, b]) => b - a)
      .map(([category, total]) => ({ category, total: Math.round(total * 100) / 100 }));
    return { content: [{ type: "text", text: JSON.stringify(sorted, null, 2) }] };
  }
);

// ── Tool: get_accounts ────────────────────────────────────────────────────────
server.tool(
  "get_accounts",
  "List all linked accounts with type, subtype, and institution info",
  {},
  async () => {
    const accounts = await fetchAccounts();
    const summary = accounts.map((a) => ({
      account_id: a.account_id,
      name: a.name,
      official_name: a.official_name,
      mask: a.mask,
      type: a.type,
      subtype: a.subtype,
    }));
    return { content: [{ type: "text", text: JSON.stringify(summary, null, 2) }] };
  }
);

// ── Tool: search_transactions ─────────────────────────────────────────────────
server.tool(
  "search_transactions",
  "Search transactions by merchant name or keyword over the past N days",
  {
    query: z.string().describe("Merchant name or keyword to search for (case-insensitive)"),
    days: z.number().int().min(1).max(730).default(90).describe("Number of days back"),
  },
  async ({ query, days }) => {
    const txns = await fetchTransactions(days);
    const q = query.toLowerCase();
    const matches = txns.filter(
      (t) =>
        (t.merchant_name ?? t.name).toLowerCase().includes(q) ||
        t.category?.some((c) => c.toLowerCase().includes(q))
    );
    const summary = matches.map((t) => ({
      date: t.date,
      name: t.merchant_name ?? t.name,
      amount: t.amount,
      category: t.personal_finance_category?.primary ?? t.category?.[0],
    }));
    return { content: [{ type: "text", text: JSON.stringify(summary, null, 2) }] };
  }
);

// ── Transport ─────────────────────────────────────────────────────────────────
const transport = process.env.MCP_TRANSPORT ?? "stdio";

if (transport === "http") {
  const port = parseInt(process.env.PORT ?? "3100", 10);
  const httpServer = createServer(async (req, res) => {
    const t = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
    res.on("close", () => t.close());
    await server.connect(t);
    await t.handleRequest(req, res);
  });
  httpServer.listen(port, () => {
    console.error(`plaid-mcp listening on http://0.0.0.0:${port}/mcp`);
  });
} else {
  const t = new StdioServerTransport();
  await server.connect(t);
}
