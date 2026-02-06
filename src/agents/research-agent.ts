import { BaseAgent } from "./base-agent";
import { AgentMessage, ResearchFact, ResearchResult, ResearchSource } from "./types";
import { MessageBus } from "@/lib/message-bus";
import { searchWeb, fetchPageContent, SearchResult } from "@/lib/web-search";
import { extractFacts } from "@/lib/fact-extractor";

const TARGET_FACTS = 7;
const MAX_PAGES_TO_FETCH = 5;

export class ResearchAgent extends BaseAgent {
  constructor(bus: MessageBus) {
    super(
      {
        id: "research",
        name: "Research Agent",
        description:
          "Searches the web for a given topic and returns 5-7 key facts with sources",
        capabilities: [
          "web-search",
          "fact-extraction",
          "source-attribution",
        ],
      },
      bus
    );
  }

  protected async process(message: AgentMessage): Promise<AgentMessage> {
    const topic = (message.payload.topic as string) ?? "general";

    const result = await this.research(topic);

    return this.createMessage(
      message.from,
      result as unknown as Record<string, unknown>,
      "response",
      message.id
    );
  }

  /**
   * Public method so the dedicated API route can call it directly
   * without going through the message bus.
   */
  async research(topic: string): Promise<ResearchResult> {
    // Build multiple search queries to get broader coverage
    const queries = this.buildQueries(topic);

    // Run all searches in parallel
    const allResults: SearchResult[] = [];
    const searchErrors: string[] = [];

    const searchPromises = queries.map(async (query) => {
      try {
        return await searchWeb(query, { maxResults: 8 });
      } catch (err) {
        searchErrors.push(
          `Query "${query}": ${err instanceof Error ? err.message : String(err)}`
        );
        return [];
      }
    });

    const searchBatches = await Promise.all(searchPromises);
    for (const batch of searchBatches) {
      allResults.push(...batch);
    }

    // Deduplicate results by URL
    const uniqueResults = this.deduplicateResults(allResults);

    // Fetch page content for the top results (in parallel, with limit)
    const pageTexts = new Map<string, string>();
    const toFetch = uniqueResults.slice(0, MAX_PAGES_TO_FETCH);

    const fetchPromises = toFetch.map(async (result) => {
      const text = await fetchPageContent(result.url);
      if (text) {
        pageTexts.set(result.url, text);
      }
    });

    await Promise.all(fetchPromises);

    // Extract facts
    const facts: ResearchFact[] = extractFacts(
      uniqueResults,
      pageTexts,
      TARGET_FACTS
    );

    // Build source list from all results that contributed facts
    const factUrls = new Set(facts.map((f) => f.sourceUrl));
    const sources: ResearchSource[] = uniqueResults
      .filter((r) => factUrls.has(r.url))
      .map((r) => ({
        title: r.title,
        url: r.url,
        snippet: r.snippet,
        retrievedAt: new Date().toISOString(),
      }));

    // Add any remaining unique results as supplementary sources
    const remaining = uniqueResults
      .filter((r) => !factUrls.has(r.url))
      .slice(0, 3);

    for (const r of remaining) {
      sources.push({
        title: r.title,
        url: r.url,
        snippet: r.snippet,
        retrievedAt: new Date().toISOString(),
      });
    }

    const summary = [
      `Research on "${topic}" complete.`,
      `Found ${facts.length} key facts from ${sources.length} sources.`,
      searchErrors.length > 0
        ? `${searchErrors.length} search query(ies) encountered errors.`
        : "",
    ]
      .filter(Boolean)
      .join(" ");

    return {
      topic,
      summary,
      facts,
      sources,
      searchQueries: queries,
      completedAt: new Date().toISOString(),
    };
  }

  private buildQueries(topic: string): string[] {
    return [
      `${topic} key facts`,
      `${topic} latest information 2025`,
      `${topic} statistics and data`,
    ];
  }

  private deduplicateResults(results: SearchResult[]): SearchResult[] {
    const seen = new Set<string>();
    const unique: SearchResult[] = [];

    for (const r of results) {
      // Normalize URL for dedup (strip trailing slash and protocol)
      const key = r.url.replace(/^https?:\/\//, "").replace(/\/$/, "");
      if (!seen.has(key)) {
        seen.add(key);
        unique.push(r);
      }
    }

    return unique;
  }
}
