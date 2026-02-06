import {
  ResearchFact,
  ResearchSource,
  ArticleTone,
  ArticleCitation,
} from "@/agents/types";

interface ComposeOptions {
  topic: string;
  facts: ResearchFact[];
  sources: ResearchSource[];
  tone: ArticleTone;
  targetWordCount: number;
}

interface ComposeResult {
  title: string;
  article: string;
  wordCount: number;
  citations: ArticleCitation[];
}

// ── Tone templates ──────────────────────────────────────────────────────

interface ToneKit {
  openingTemplates: string[];
  transitionPhrases: string[];
  closingTemplates: string[];
  citationVerbs: string[];
}

const TONE_KITS: Record<ArticleTone, ToneKit> = {
  professional: {
    openingTemplates: [
      "In today's rapidly evolving landscape, {topic} continues to reshape how organizations and professionals approach key challenges.",
      "As industries worldwide adapt to shifting priorities, {topic} has emerged as a critical area demanding attention from decision-makers.",
    ],
    transitionPhrases: [
      "Furthermore,",
      "Significantly,",
      "Building on this,",
      "It is also worth noting that",
      "Equally important,",
      "In addition,",
    ],
    closingTemplates: [
      "As the landscape around {topic} continues to evolve, staying informed and adaptable will be essential for professionals and organizations seeking to maintain a competitive edge.",
      "Looking ahead, the developments surrounding {topic} suggest a trajectory that will require ongoing attention and strategic planning from all stakeholders involved.",
    ],
    citationVerbs: [
      "According to {source},",
      "As reported by {source},",
      "Research from {source} indicates that",
      "Analysis by {source} reveals that",
      "Data from {source} shows that",
    ],
  },
  casual: {
    openingTemplates: [
      "If you've been paying attention lately, you've probably noticed that {topic} is kind of everywhere — and for good reason.",
      "So, {topic} — what's the deal? Turns out there's a lot more going on than you might think.",
    ],
    transitionPhrases: [
      "Here's the thing —",
      "What's interesting is that",
      "On top of that,",
      "And get this:",
      "But wait, there's more.",
      "It doesn't stop there.",
    ],
    closingTemplates: [
      "Bottom line? {topic} isn't going anywhere, and it's worth keeping an eye on how things unfold from here.",
      "All in all, {topic} is shaping up to be one of those things you'll want to stay curious about — there's clearly more to come.",
    ],
    citationVerbs: [
      "According to {source},",
      "Over at {source}, they found that",
      "As {source} points out,",
      "{source} notes that",
      "The folks at {source} report that",
    ],
  },
  academic: {
    openingTemplates: [
      "The domain of {topic} has attracted considerable scholarly attention in recent years, prompting a re-examination of established paradigms and methodologies.",
      "Contemporary discourse on {topic} reflects a growing body of evidence that challenges prior assumptions and introduces novel analytical frameworks.",
    ],
    transitionPhrases: [
      "Moreover,",
      "Notably,",
      "Complementing this finding,",
      "Of particular significance,",
      "A further dimension emerges when considering that",
      "Corroborating this perspective,",
    ],
    closingTemplates: [
      "In summation, the current trajectory of {topic} underscores the necessity for continued interdisciplinary inquiry and evidence-based policy formulation.",
      "The evidence reviewed herein suggests that {topic} warrants sustained scholarly attention, with implications extending across multiple domains of practice and theory.",
    ],
    citationVerbs: [
      "As documented by {source},",
      "Research published by {source} demonstrates that",
      "Findings from {source} indicate that",
      "{source} has established that",
      "According to {source},",
    ],
  },
  journalistic: {
    openingTemplates: [
      "A wave of new developments in {topic} is drawing attention from experts, industry leaders, and the public alike — raising questions about what comes next.",
      "From boardrooms to research labs, {topic} is making headlines as new data paints a clearer picture of its growing impact.",
    ],
    transitionPhrases: [
      "Meanwhile,",
      "In a related development,",
      "Sources also indicate that",
      "Adding to the picture,",
      "At the same time,",
      "Reports also suggest that",
    ],
    closingTemplates: [
      "As the story around {topic} continues to develop, observers say the coming months will be pivotal in determining its long-term trajectory.",
      "With {topic} firmly in the spotlight, experts agree: the conversation is far from over, and the stakes are only getting higher.",
    ],
    citationVerbs: [
      "According to {source},",
      "As reported by {source},",
      "{source} found that",
      "A report from {source} reveals that",
      "Sources at {source} confirm that",
    ],
  },
};

// ── Composer ─────────────────────────────────────────────────────────────

export function composeArticle(options: ComposeOptions): ComposeResult {
  const { topic, facts, sources, tone, targetWordCount } = options;
  const kit = TONE_KITS[tone];

  // Build a citation index: map sourceUrl → citation number
  const citationMap = new Map<string, ArticleCitation>();
  let citationIndex = 1;

  for (const fact of facts) {
    if (!citationMap.has(fact.sourceUrl)) {
      citationMap.set(fact.sourceUrl, {
        index: citationIndex++,
        sourceTitle: fact.sourceTitle,
        sourceUrl: fact.sourceUrl,
      });
    }
  }

  const citations = Array.from(citationMap.values());

  // ── Title ────────────────────────────────────────────────────────────
  const title = generateTitle(topic, tone);

  // ── Body paragraphs ──────────────────────────────────────────────────
  const paragraphs: string[] = [];

  // Opening paragraph
  const opening = pickRandom(kit.openingTemplates).replace(
    /\{topic\}/g,
    topic
  );
  paragraphs.push(opening);

  // Body paragraphs — weave in facts with citations
  // Group facts into paragraphs (2-3 facts per paragraph)
  const grouped = groupFacts(facts, 2);

  for (let g = 0; g < grouped.length; g++) {
    const group = grouped[g];
    const sentences: string[] = [];

    for (let i = 0; i < group.length; i++) {
      const fact = group[i];
      const citation = citationMap.get(fact.sourceUrl)!;
      const citRef = `[${citation.index}]`;

      if (i === 0 && g > 0) {
        // Lead with a transition
        const transition = kit.transitionPhrases[g % kit.transitionPhrases.length];
        const citVerb = pickRandom(kit.citationVerbs).replace(
          /\{source\}/g,
          fact.sourceTitle
        );
        sentences.push(`${transition} ${lowerFirst(citVerb)} ${lowerFirst(cleanFact(fact.fact))} ${citRef}`);
      } else if (i === 0) {
        // First fact in first body paragraph — use citation verb
        const citVerb = pickRandom(kit.citationVerbs).replace(
          /\{source\}/g,
          fact.sourceTitle
        );
        sentences.push(`${citVerb} ${lowerFirst(cleanFact(fact.fact))} ${citRef}`);
      } else {
        // Subsequent fact in same paragraph
        sentences.push(`${upperFirst(cleanFact(fact.fact))} ${citRef}`);
      }
    }

    paragraphs.push(sentences.join(" "));
  }

  // If we're short of target, add a context paragraph
  const currentWords = paragraphs.join(" ").split(/\s+/).length;
  if (currentWords < targetWordCount * 0.7) {
    const filler = generateContextParagraph(topic, sources, kit);
    paragraphs.push(filler);
  }

  // Closing paragraph
  const closing = pickRandom(kit.closingTemplates).replace(
    /\{topic\}/g,
    topic
  );
  paragraphs.push(closing);

  // ── References section ───────────────────────────────────────────────
  const refsSection = citations
    .map((c) => `[${c.index}] ${c.sourceTitle} — ${c.sourceUrl}`)
    .join("\n");

  const article = paragraphs.join("\n\n") + "\n\n---\nSources:\n" + refsSection;

  return {
    title,
    article,
    wordCount: article.split(/\s+/).length,
    citations,
  };
}

// ── Helpers ──────────────────────────────────────────────────────────────

function generateTitle(topic: string, tone: ArticleTone): string {
  const templates: Record<ArticleTone, string[]> = {
    professional: [
      `${upperFirst(topic)}: Key Developments and What They Mean`,
      `The State of ${upperFirst(topic)}: An Overview`,
    ],
    casual: [
      `What You Need to Know About ${upperFirst(topic)}`,
      `${upperFirst(topic)}: Here's What's Going On`,
    ],
    academic: [
      `A Contemporary Analysis of ${upperFirst(topic)}`,
      `${upperFirst(topic)}: Current Findings and Implications`,
    ],
    journalistic: [
      `Inside ${upperFirst(topic)}: What the Latest Data Reveals`,
      `${upperFirst(topic)} in Focus: Facts, Figures, and What's Next`,
    ],
  };
  return pickRandom(templates[tone]);
}

function generateContextParagraph(
  topic: string,
  sources: ResearchSource[],
  kit: ToneKit
): string {
  const snippets = sources
    .filter((s) => s.snippet.length > 40)
    .slice(0, 2);

  if (snippets.length === 0) {
    return `${pickRandom(kit.transitionPhrases)} the broader context around ${topic} reveals a landscape of ongoing change and increasing relevance across multiple sectors.`;
  }

  const parts = snippets.map(
    (s) => cleanFact(s.snippet.split(/(?<=[.!?])\s+/)[0] ?? s.snippet)
  );

  return `${pickRandom(kit.transitionPhrases)} a broader view of ${topic} shows that ${lowerFirst(parts[0])}${parts[1] ? ` Further, ${lowerFirst(parts[1])}` : ""}`;
}

function groupFacts<T>(items: T[], perGroup: number): T[][] {
  const groups: T[][] = [];
  for (let i = 0; i < items.length; i += perGroup) {
    groups.push(items.slice(i, i + perGroup));
  }
  return groups;
}

function cleanFact(text: string): string {
  // Trim trailing/leading junk and ensure it ends with a period
  let cleaned = text.replace(/\s+/g, " ").trim();
  if (!/[.!?]$/.test(cleaned)) {
    cleaned += ".";
  }
  return cleaned;
}

function pickRandom<T>(arr: T[]): T {
  return arr[Math.floor(Math.random() * arr.length)];
}

function lowerFirst(s: string): string {
  if (!s) return s;
  return s[0].toLowerCase() + s.slice(1);
}

function upperFirst(s: string): string {
  if (!s) return s;
  return s[0].toUpperCase() + s.slice(1);
}
