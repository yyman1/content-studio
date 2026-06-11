import "dotenv/config";
import { createServer } from "http";
import { plaid } from "./plaid-client.js";

const PORT = 3101;

const html = `<!DOCTYPE html>
<html>
<head><title>Plaid Link</title></head>
<body>
<h2>Plaid Link — get access token</h2>
<button id="btn">Connect a bank account</button>
<pre id="out"></pre>
<script src="https://cdn.plaid.com/link/v2/stable/link-initialize.js"></script>
<script>
  document.getElementById('btn').onclick = async () => {
    const res = await fetch('/create-link-token', { method: 'POST' });
    const { link_token } = await res.json();
    const handler = Plaid.create({
      token: link_token,
      onSuccess: async (public_token) => {
        const r = await fetch('/exchange', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ public_token }),
        });
        const data = await r.json();
        document.getElementById('out').textContent =
          'Add this to your .env:\\n\\nPLAID_ACCESS_TOKENS=' + data.access_token;
      },
      onExit: (err) => { if (err) console.error(err); },
    });
    handler.open();
  };
</script>
</body>
</html>`;

const server = createServer(async (req, res) => {
  if (req.method === "GET" && req.url === "/") {
    res.writeHead(200, { "Content-Type": "text/html" });
    res.end(html);
    return;
  }

  if (req.method === "POST" && req.url === "/create-link-token") {
    const r = await plaid.linkTokenCreate({
      user: { client_user_id: "local-user" },
      client_name: "plaid-mcp",
      products: ["transactions"],
      country_codes: ["US"] as any,
      language: "en",
    });
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ link_token: r.data.link_token }));
    return;
  }

  if (req.method === "POST" && req.url === "/exchange") {
    const body: Buffer[] = [];
    req.on("data", (chunk) => body.push(chunk));
    req.on("end", async () => {
      const { public_token } = JSON.parse(Buffer.concat(body).toString());
      const r = await plaid.itemPublicTokenExchange({ public_token });
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ access_token: r.data.access_token }));
    });
    return;
  }

  res.writeHead(404);
  res.end();
});

server.listen(PORT, () => {
  console.log(`Open http://localhost:${PORT} in your browser`);
});
