import * as cheerio from "cheerio";

export interface SearchResult {
  title: string;
  url: string;
  snippet: string;
}

export interface SearchOptions {
  maxResults?: number;
  region?: string;
}

const USER_AGENT =
  "ContentStudio/1.0 (Multi-Agent Research Pipeline; contact@example.com)";

/**
 * Search the web using multiple strategies with automatic fallback.
 * Order: DuckDuckGo HTML → DuckDuckGo Lite → Wikipedia API
 */
export async function searchWeb(
  query: string,
  options: SearchOptions = {}
): Promise<SearchResult[]> {
  const { maxResults = 10 } = options;

  // Strategy 1: DuckDuckGo HTML
  try {
    const results = await searchDuckDuckGoHtml(query, maxResults);
    if (results.length > 0) return results;
  } catch {
    // Fall through to next strategy
  }

  // Strategy 2: DuckDuckGo Lite (different endpoint, sometimes less restricted)
  try {
    const results = await searchDuckDuckGoLite(query, maxResults);
    if (results.length > 0) return results;
  } catch {
    // Fall through to next strategy
  }

  // Strategy 3: Wikipedia API (always works from serverless)
  try {
    const results = await searchWikipedia(query, maxResults);
    if (results.length > 0) return results;
  } catch {
    // All strategies failed
  }

  return [];
}

// ── DuckDuckGo HTML ──────────────────────────────────────────────────────

async function searchDuckDuckGoHtml(
  query: string,
  maxResults: number
): Promise<SearchResult[]> {
  const params = new URLSearchParams({ q: query, kl: "us-en" });

  const response = await fetch(`https://html.duckduckgo.com/html/?${params}`, {
    method: "POST",
    headers: {
      "User-Agent": USER_AGENT,
      Accept: "text/html",
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: params.toString(),
  });

  if (!response.ok) {
    throw new Error(`DuckDuckGo HTML: ${response.status}`);
  }

  const html = await response.text();

  // Detect if we got a bot-block page
  if (html.includes("blocked") || html.includes("bot") || html.length < 1000) {
    throw new Error("DuckDuckGo HTML: blocked");
  }

  return parseDuckDuckGoHtml(html, maxResults);
}

function parseDuckDuckGoHtml(html: string, maxResults: number): SearchResult[] {
  const $ = cheerio.load(html);
  const results: SearchResult[] = [];

  $(".result").each((_i, element) => {
    if (results.length >= maxResults) return false;

    const $el = $(element);
    const titleEl = $el.find(".result__title .result__a");
    const snippetEl = $el.find(".result__snippet");
    const urlEl = $el.find(".result__url");

    const title = titleEl.text().trim();
    let url = titleEl.attr("href") ?? "";
    const snippet = snippetEl.text().trim();

    if (url.includes("uddg=")) {
      try {
        const parsed = new URL(url, "https://duckduckgo.com");
        url = decodeURIComponent(parsed.searchParams.get("uddg") ?? url);
      } catch {
        url = `https://${urlEl.text().trim()}`;
      }
    }

    if (title && snippet) {
      results.push({ title, url, snippet });
    }
  });

  return results;
}

// ── DuckDuckGo Lite ──────────────────────────────────────────────────────

async function searchDuckDuckGoLite(
  query: string,
  maxResults: number
): Promise<SearchResult[]> {
  const params = new URLSearchParams({ q: query });

  const response = await fetch("https://lite.duckduckgo.com/lite/", {
    method: "POST",
    headers: {
      "User-Agent": USER_AGENT,
      Accept: "text/html",
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: params.toString(),
  });

  if (!response.ok) {
    throw new Error(`DuckDuckGo Lite: ${response.status}`);
  }

  const html = await response.text();

  if (html.includes("blocked") || html.length < 500) {
    throw new Error("DuckDuckGo Lite: blocked");
  }

  return parseDuckDuckGoLite(html, maxResults);
}

function parseDuckDuckGoLite(html: string, maxResults: number): SearchResult[] {
  const $ = cheerio.load(html);
  const results: SearchResult[] = [];

  // Lite format uses table rows with specific classes
  const rows = $("table:last-of-type tr");

  let current: Partial<SearchResult> = {};

  rows.each((_i, row) => {
    if (results.length >= maxResults) return false;

    const $row = $(row);

    // Title/link row
    const link = $row.find("a.result-link");
    if (link.length) {
      current = {
        title: link.text().trim(),
        url: link.attr("href") ?? "",
      };
      return;
    }

    // Snippet row
    const snippet = $row.find("td.result-snippet");
    if (snippet.length && current.title) {
      current.snippet = snippet.text().trim();
      if (current.title && current.url && current.snippet) {
        results.push(current as SearchResult);
      }
      current = {};
    }
  });

  return results;
}

// ── Wikipedia API ────────────────────────────────────────────────────────

async function searchWikipedia(
  query: string,
  maxResults: number
): Promise<SearchResult[]> {
  const params = new URLSearchParams({
    action: "query",
    format: "json",
    list: "search",
    srsearch: query,
    srlimit: String(Math.min(maxResults, 10)),
    srprop: "snippet|titlesnippet",
    utf8: "1",
    origin: "*",
  });

  const response = await fetch(
    `https://en.wikipedia.org/w/api.php?${params}`,
    {
      headers: { "User-Agent": USER_AGENT, Accept: "application/json" },
    }
  );

  if (!response.ok) {
    throw new Error(`Wikipedia API: ${response.status}`);
  }

  const data = await response.json();
  const searchResults: Array<{ title: string; snippet: string; pageid: number }> =
    data?.query?.search ?? [];

  // For each result, fetch the extract (first paragraph) for richer content
  const results: SearchResult[] = [];

  // Batch fetch extracts for all pages
  if (searchResults.length > 0) {
    const titles = searchResults.map((r) => r.title).join("|");
    const extractParams = new URLSearchParams({
      action: "query",
      format: "json",
      titles: titles,
      prop: "extracts|info",
      exintro: "1",
      explaintext: "1",
      exsentences: "5",
      inprop: "url",
      origin: "*",
    });

    const extractResponse = await fetch(
      `https://en.wikipedia.org/w/api.php?${extractParams}`,
      {
        headers: { "User-Agent": USER_AGENT, Accept: "application/json" },
      }
    );

    if (extractResponse.ok) {
      const extractData = await extractResponse.json();
      const pages: Record<
        string,
        { title: string; extract?: string; fullurl?: string }
      > = extractData?.query?.pages ?? {};

      // Build a lookup by title
      const extractsByTitle = new Map<string, { extract: string; url: string }>();
      for (const page of Object.values(pages)) {
        if (page.extract && page.fullurl) {
          extractsByTitle.set(page.title, {
            extract: page.extract,
            url: page.fullurl,
          });
        }
      }

      for (const sr of searchResults) {
        const ext = extractsByTitle.get(sr.title);
        // Strip HTML from the search snippet
        const cleanSnippet = sr.snippet.replace(/<[^>]+>/g, "");

        results.push({
          title: `${sr.title} - Wikipedia`,
          url:
            ext?.url ??
            `https://en.wikipedia.org/wiki/${encodeURIComponent(sr.title.replace(/ /g, "_"))}`,
          snippet: ext?.extract ?? cleanSnippet,
        });
      }
    }
  }

  return results;
}

/**
 * Fetch a webpage and extract its main text content.
 * Used to gather deeper facts from individual search results.
 */
export async function fetchPageContent(
  url: string,
  maxLength = 5000
): Promise<string> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8000);

  try {
    const response = await fetch(url, {
      headers: { "User-Agent": USER_AGENT, Accept: "text/html" },
      signal: controller.signal,
      redirect: "follow",
    });

    if (!response.ok) return "";

    const html = await response.text();
    const $ = cheerio.load(html);

    // Remove non-content elements
    $("script, style, nav, header, footer, aside, iframe, noscript").remove();

    // Extract text from likely content areas
    const contentSelectors = [
      "article",
      '[role="main"]',
      "main",
      ".post-content",
      ".article-body",
      ".entry-content",
    ];

    let text = "";
    for (const selector of contentSelectors) {
      const el = $(selector);
      if (el.length) {
        text = el.text();
        break;
      }
    }

    // Fallback to body text
    if (!text) {
      text = $("body").text();
    }

    // Clean up whitespace
    text = text.replace(/\s+/g, " ").trim();

    return text.slice(0, maxLength);
  } catch {
    return "";
  } finally {
    clearTimeout(timeout);
  }
}
