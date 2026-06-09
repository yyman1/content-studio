import {
  Configuration,
  PlaidApi,
  PlaidEnvironments,
  type AccountBase,
  type Transaction,
} from "plaid";

const env = process.env.PLAID_ENV ?? "sandbox";
const config = new Configuration({
  basePath: PlaidEnvironments[env as keyof typeof PlaidEnvironments],
  baseOptions: {
    headers: {
      "PLAID-CLIENT-ID": process.env.PLAID_CLIENT_ID!,
      "PLAID-SECRET": process.env.PLAID_SECRET!,
    },
  },
});

export const plaid = new PlaidApi(config);

export function getAccessTokens(): string[] {
  const raw = process.env.PLAID_ACCESS_TOKENS ?? "";
  return raw
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

export async function fetchBalances(): Promise<AccountBase[]> {
  const tokens = getAccessTokens();
  const results = await Promise.all(
    tokens.map((access_token) =>
      plaid.accountsBalanceGet({ access_token }).then((r) => r.data.accounts)
    )
  );
  return results.flat();
}

export async function fetchTransactions(
  days: number
): Promise<Transaction[]> {
  const tokens = getAccessTokens();
  const end = new Date();
  const start = new Date();
  start.setDate(end.getDate() - days);

  const fmt = (d: Date) => d.toISOString().slice(0, 10);

  const results = await Promise.all(
    tokens.map(async (access_token) => {
      let txns: Transaction[] = [];
      let cursor: string | undefined;

      // Paginate using /transactions/sync
      while (true) {
        const res = await plaid.transactionsSync({
          access_token,
          cursor,
          count: 500,
        });
        txns = txns.concat(res.data.added);
        if (!res.data.has_more) break;
        cursor = res.data.next_cursor;
      }

      // Filter to requested date window
      return txns.filter(
        (t) => t.date >= fmt(start) && t.date <= fmt(end)
      );
    })
  );

  return results
    .flat()
    .sort((a, b) => (a.date < b.date ? 1 : -1)); // newest first
}

export async function fetchAccounts(): Promise<AccountBase[]> {
  const tokens = getAccessTokens();
  const results = await Promise.all(
    tokens.map((access_token) =>
      plaid.accountsGet({ access_token }).then((r) => r.data.accounts)
    )
  );
  return results.flat();
}
