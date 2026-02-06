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
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

/**
 * Search the web using DuckDuckGo HTML and parse the results.
 * No API key required.
 */
export async function searchWeb(
  query: string,
  options: SearchOptions = {}
): Promise<SearchResult[]> {
  const { maxResults = 10, region = "us-en" } = options;

  const params = new URLSearchParams({
    q: query,
    kl: region,
  });

  const response = await fetch(`https://html.duckduckgo.com/html/?${params}`, {
    method: "GET",
    headers: {
      "User-Agent": USER_AGENT,
      Accept: "text/html",
      "Accept-Language": "en-US,en;q=0.9",
    },
  });

  if (!response.ok) {
    throw new Error(`Search request failed with status ${response.status}`);
  }

  const html = await response.text();
  return parseSearchResults(html, maxResults);
}

function parseSearchResults(html: string, maxResults: number): SearchResult[] {
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

    // DuckDuckGo wraps URLs in a redirect — extract the real URL
    if (url.includes("uddg=")) {
      try {
        const parsed = new URL(url, "https://duckduckgo.com");
        url = decodeURIComponent(parsed.searchParams.get("uddg") ?? url);
      } catch {
        // If URL parsing fails, try the displayed URL instead
        url = `https://${urlEl.text().trim()}`;
      }
    }

    if (title && snippet) {
      results.push({ title, url, snippet });
    }
  });

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
