import { SearchResult } from "./web-search";
import { ResearchFact } from "@/agents/types";

/**
 * Extract distinct factual statements from search result snippets
 * and optionally from fetched page content.
 *
 * Applies heuristics to pick the most informative, non-duplicate sentences.
 */
export function extractFacts(
  results: SearchResult[],
  pageTexts: Map<string, string>,
  targetCount: number
): ResearchFact[] {
  const candidates: Array<{
    sentence: string;
    sourceUrl: string;
    sourceTitle: string;
    score: number;
  }> = [];

  for (const result of results) {
    // Sentences from snippet
    const snippetSentences = splitSentences(result.snippet);
    for (const s of snippetSentences) {
      candidates.push({
        sentence: s,
        sourceUrl: result.url,
        sourceTitle: result.title,
        score: scoreSentence(s),
      });
    }

    // Sentences from fetched page content (boosted slightly less to avoid noise)
    const pageText = pageTexts.get(result.url);
    if (pageText) {
      const pageSentences = splitSentences(pageText).slice(0, 20); // limit to first 20
      for (const s of pageSentences) {
        candidates.push({
          sentence: s,
          sourceUrl: result.url,
          sourceTitle: result.title,
          score: scoreSentence(s) * 0.8,
        });
      }
    }
  }

  // Sort by score descending, then deduplicate
  candidates.sort((a, b) => b.score - a.score);

  const facts: ResearchFact[] = [];
  const seen = new Set<string>();

  for (const c of candidates) {
    if (facts.length >= targetCount) break;

    const normalized = c.sentence.toLowerCase().replace(/\s+/g, " ").trim();
    // Skip very short sentences or ones too similar to already-selected facts
    if (normalized.length < 30) continue;
    if (isDuplicate(normalized, seen)) continue;

    seen.add(normalized);
    facts.push({
      fact: c.sentence,
      sourceUrl: c.sourceUrl,
      sourceTitle: c.sourceTitle,
    });
  }

  return facts;
}

function splitSentences(text: string): string[] {
  return text
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 15);
}

/**
 * Score a sentence based on how "factual" and informative it appears.
 * Higher is better.
 */
function scoreSentence(sentence: string): number {
  let score = 0;

  // Length bonus (prefer medium-length sentences)
  if (sentence.length > 40 && sentence.length < 300) score += 3;
  else if (sentence.length >= 300) score += 1;

  // Contains numbers (dates, stats, percentages)
  if (/\d/.test(sentence)) score += 4;

  // Contains percentage or dollar sign
  if (/%|\$/.test(sentence)) score += 3;

  // Contains specific factual indicators
  if (/according to|study|report|research|found that|data shows/i.test(sentence))
    score += 3;

  // Contains a year (2000+)
  if (/20[0-2]\d/.test(sentence)) score += 2;

  // Penalty for questions
  if (sentence.endsWith("?")) score -= 5;

  // Penalty for vague or promotional language
  if (/click here|sign up|subscribe|buy now|best ever/i.test(sentence))
    score -= 10;

  // Penalty for cookie/privacy notices
  if (/cookie|privacy policy|consent/i.test(sentence)) score -= 10;

  return score;
}

function isDuplicate(normalized: string, seen: Set<string>): boolean {
  for (const existing of seen) {
    // Simple overlap check: if >60% of words overlap, consider duplicate
    const wordsA = new Set(normalized.split(/\s+/));
    const wordsB = new Set(existing.split(/\s+/));
    const intersection = [...wordsA].filter((w) => wordsB.has(w));
    const overlap = intersection.length / Math.min(wordsA.size, wordsB.size);
    if (overlap > 0.6) return true;
  }
  return false;
}
