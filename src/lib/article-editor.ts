import { ArticleTone, EditChange, QualityScore } from "@/agents/types";

export interface EditOptions {
  article: string;
  title: string;
  topic: string;
  tone: ArticleTone;
}

export interface EditResult {
  editedArticle: string;
  editedTitle: string;
  headlineSuggestions: string[];
  changes: EditChange[];
  qualityScore: QualityScore;
}

// ── Grammar rules ────────────────────────────────────────────────────────

interface PatternRule {
  pattern: RegExp;
  replacement: string | ((match: string, ...groups: string[]) => string);
  reason: string;
  type: EditChange["type"];
}

const GRAMMAR_RULES: PatternRule[] = [
  {
    pattern: /\b(its|it's)\s+(a|an|the|very|quite|not|also|more)\b/gi,
    replacement: (_m, contraction, next) => `it's ${next}`,
    reason: "Corrected \"its\" to \"it's\" (contraction of \"it is\")",
    type: "grammar",
  },
  {
    pattern: /\b(\w+)\s+\1\b/gi,
    replacement: "$1",
    reason: "Removed accidental word duplication",
    type: "grammar",
  },
  {
    pattern: /\s+,/g,
    replacement: ",",
    reason: "Removed extra space before comma",
    type: "grammar",
  },
  {
    pattern: /,\s*,/g,
    replacement: ",",
    reason: "Removed duplicate comma",
    type: "grammar",
  },
  {
    pattern: /\.\s*\./g,
    replacement: ".",
    reason: "Removed duplicate period",
    type: "grammar",
  },
  {
    pattern: /\s{2,}/g,
    replacement: " ",
    reason: "Normalized extra whitespace",
    type: "grammar",
  },
];

// ── Clarity rules ────────────────────────────────────────────────────────

const CLARITY_RULES: PatternRule[] = [
  {
    pattern: /\bdue to the fact that\b/gi,
    replacement: "because",
    reason: "Replaced wordy phrase with concise alternative",
    type: "clarity",
  },
  {
    pattern: /\bin order to\b/gi,
    replacement: "to",
    reason: "Simplified \"in order to\" to \"to\"",
    type: "clarity",
  },
  {
    pattern: /\bat this point in time\b/gi,
    replacement: "now",
    reason: "Simplified \"at this point in time\" to \"now\"",
    type: "clarity",
  },
  {
    pattern: /\bfor the purpose of\b/gi,
    replacement: "to",
    reason: "Simplified \"for the purpose of\" to \"to\"",
    type: "clarity",
  },
  {
    pattern: /\bin the event that\b/gi,
    replacement: "if",
    reason: "Simplified \"in the event that\" to \"if\"",
    type: "clarity",
  },
  {
    pattern: /\bhas the ability to\b/gi,
    replacement: "can",
    reason: "Simplified \"has the ability to\" to \"can\"",
    type: "clarity",
  },
  {
    pattern: /\bin light of the fact that\b/gi,
    replacement: "because",
    reason: "Simplified \"in light of the fact that\" to \"because\"",
    type: "clarity",
  },
  {
    pattern: /\bit is important to note that\b/gi,
    replacement: "Notably,",
    reason: "Tightened filler phrase",
    type: "clarity",
  },
  {
    pattern: /\bit is worth mentioning that\b/gi,
    replacement: "Notably,",
    reason: "Tightened filler phrase",
    type: "clarity",
  },
  {
    pattern: /\ba large number of\b/gi,
    replacement: "many",
    reason: "Simplified \"a large number of\" to \"many\"",
    type: "clarity",
  },
  {
    pattern: /\bthe vast majority of\b/gi,
    replacement: "most",
    reason: "Simplified \"the vast majority of\" to \"most\"",
    type: "clarity",
  },
  {
    pattern: /\bin spite of\b/gi,
    replacement: "despite",
    reason: "Simplified \"in spite of\" to \"despite\"",
    type: "clarity",
  },
  {
    pattern: /\bwith regard to\b/gi,
    replacement: "regarding",
    reason: "Simplified \"with regard to\" to \"regarding\"",
    type: "clarity",
  },
  {
    pattern: /\bon a daily basis\b/gi,
    replacement: "daily",
    reason: "Simplified \"on a daily basis\" to \"daily\"",
    type: "clarity",
  },
];

// ── Redundancy rules ─────────────────────────────────────────────────────

const REDUNDANCY_RULES: PatternRule[] = [
  {
    pattern: /\bcompletely eliminate\b/gi,
    replacement: "eliminate",
    reason: "Removed redundant modifier (eliminate already implies completeness)",
    type: "redundancy",
  },
  {
    pattern: /\bpast history\b/gi,
    replacement: "history",
    reason: "Removed redundant \"past\" (history is inherently past)",
    type: "redundancy",
  },
  {
    pattern: /\bfuture plans\b/gi,
    replacement: "plans",
    reason: "Removed redundant \"future\" (plans are inherently future)",
    type: "redundancy",
  },
  {
    pattern: /\bend result\b/gi,
    replacement: "result",
    reason: "Removed redundant \"end\" before \"result\"",
    type: "redundancy",
  },
  {
    pattern: /\bfree gift\b/gi,
    replacement: "gift",
    reason: "Removed redundant \"free\" (gifts are free by definition)",
    type: "redundancy",
  },
  {
    pattern: /\beach and every\b/gi,
    replacement: "every",
    reason: "Simplified \"each and every\" to \"every\"",
    type: "redundancy",
  },
  {
    pattern: /\bfirst and foremost\b/gi,
    replacement: "first",
    reason: "Simplified \"first and foremost\" to \"first\"",
    type: "redundancy",
  },
  {
    pattern: /\bbasic fundamentals\b/gi,
    replacement: "fundamentals",
    reason: "Removed redundant \"basic\" before \"fundamentals\"",
    type: "redundancy",
  },
  {
    pattern: /\bvery unique\b/gi,
    replacement: "unique",
    reason: "Removed \"very\" (unique is absolute and cannot be qualified)",
    type: "redundancy",
  },
];

// ── Headline generation ──────────────────────────────────────────────────

const HEADLINE_TEMPLATES: Record<ArticleTone, ((topic: string) => string)[]> = {
  professional: [
    (t) => `Why ${cap(t)} Matters More Than Ever`,
    (t) => `${cap(t)}: The Trends Shaping What Comes Next`,
    (t) => `What Leaders Need to Know About ${cap(t)}`,
  ],
  casual: [
    (t) => `${cap(t)} Is Changing Fast — Here's the Scoop`,
    (t) => `The Lowdown on ${cap(t)}: What's Really Going On`,
    (t) => `Everything You're Missing About ${cap(t)}`,
  ],
  academic: [
    (t) => `Revisiting ${cap(t)}: An Evidence-Based Perspective`,
    (t) => `${cap(t)} Under the Microscope: Findings and Implications`,
    (t) => `New Dimensions in ${cap(t)} Research`,
  ],
  journalistic: [
    (t) => `${cap(t)}: The Numbers Behind the Headlines`,
    (t) => `What the Data Reveals About ${cap(t)}`,
    (t) => `${cap(t)} at a Crossroads: Key Facts and What's Ahead`,
  ],
};

function cap(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// ── Structure improvements ───────────────────────────────────────────────

function improveStructure(article: string): { text: string; changes: EditChange[] } {
  const changes: EditChange[] = [];
  let text = article;

  // Split into paragraphs
  const paragraphs = text.split(/\n\n+/);

  // Flag very long paragraphs (>120 words) — suggest a break
  const improved: string[] = [];
  for (const para of paragraphs) {
    const words = para.split(/\s+/);
    if (words.length > 120) {
      // Split around the middle sentence boundary
      const sentences = para.split(/(?<=[.!?])\s+/);
      const mid = Math.ceil(sentences.length / 2);
      const firstHalf = sentences.slice(0, mid).join(" ");
      const secondHalf = sentences.slice(mid).join(" ");

      if (secondHalf.length > 0) {
        improved.push(firstHalf, secondHalf);
        changes.push({
          type: "structure",
          original: para.slice(0, 60) + "...",
          replacement: firstHalf.slice(0, 40) + "... [paragraph split]",
          reason: `Split long paragraph (${words.length} words) into two for better readability`,
        });
      } else {
        improved.push(para);
      }
    } else {
      improved.push(para);
    }
  }

  text = improved.join("\n\n");
  return { text, changes };
}

// ── Quality scoring ──────────────────────────────────────────────────────

function scoreArticle(article: string, changeCount: number): QualityScore {
  const sentences = article.split(/(?<=[.!?])\s+/).filter((s) => s.length > 5);
  const words = article.split(/\s+/);
  const avgSentenceLen = words.length / Math.max(sentences.length, 1);

  // Grammar: start high, deduct for changes applied
  const grammarScore = Math.max(60, 95 - changeCount * 2);

  // Clarity: based on average sentence length (ideal 15-25 words)
  let clarityScore = 90;
  if (avgSentenceLen > 30) clarityScore -= (avgSentenceLen - 30) * 2;
  if (avgSentenceLen < 8) clarityScore -= (8 - avgSentenceLen) * 3;
  clarityScore = Math.max(50, Math.min(98, clarityScore));

  // Structure: based on paragraph count vs word count
  const paraCount = article.split(/\n\n+/).length;
  const idealParas = Math.max(3, Math.round(words.length / 75));
  const paraDiff = Math.abs(paraCount - idealParas);
  const structureScore = Math.max(55, 95 - paraDiff * 5);

  // Engagement: check for varied sentence starters and questions
  const starters = new Set(
    sentences.slice(0, 10).map((s) => s.split(/\s+/)[0]?.toLowerCase())
  );
  const starterVariety = starters.size / Math.min(sentences.length, 10);
  const hasQuestion = sentences.some((s) => s.trim().endsWith("?"));
  let engagementScore = Math.round(starterVariety * 80);
  if (hasQuestion) engagementScore += 10;
  engagementScore = Math.max(50, Math.min(98, engagementScore));

  const overall = Math.round(
    grammarScore * 0.25 +
      clarityScore * 0.3 +
      structureScore * 0.2 +
      engagementScore * 0.25
  );

  return {
    overall,
    grammar: grammarScore,
    clarity: Math.round(clarityScore),
    structure: structureScore,
    engagement: engagementScore,
  };
}

// ── Main editor function ─────────────────────────────────────────────────

export function editArticle(options: EditOptions): EditResult {
  const { article, title, topic, tone } = options;

  let editedText = article;
  const allChanges: EditChange[] = [];

  // 1. Apply grammar rules
  for (const rule of GRAMMAR_RULES) {
    const matches = editedText.match(rule.pattern);
    if (matches) {
      for (const match of matches) {
        const replaced =
          typeof rule.replacement === "function"
            ? match.replace(rule.pattern, rule.replacement as (...args: string[]) => string)
            : match.replace(rule.pattern, rule.replacement);
        if (replaced !== match) {
          allChanges.push({
            type: rule.type,
            original: match,
            replacement: replaced,
            reason: rule.reason,
          });
        }
      }
      editedText = editedText.replace(
        rule.pattern,
        rule.replacement as string
      );
    }
  }

  // 2. Apply clarity rules
  for (const rule of CLARITY_RULES) {
    const matches = editedText.match(rule.pattern);
    if (matches) {
      for (const match of matches) {
        allChanges.push({
          type: rule.type,
          original: match,
          replacement: typeof rule.replacement === "string" ? rule.replacement : match,
          reason: rule.reason,
        });
      }
      editedText = editedText.replace(
        rule.pattern,
        rule.replacement as string
      );
    }
  }

  // 3. Apply redundancy rules
  for (const rule of REDUNDANCY_RULES) {
    const matches = editedText.match(rule.pattern);
    if (matches) {
      for (const match of matches) {
        allChanges.push({
          type: rule.type,
          original: match,
          replacement: rule.replacement as string,
          reason: rule.reason,
        });
      }
      editedText = editedText.replace(
        rule.pattern,
        rule.replacement as string
      );
    }
  }

  // 4. Improve structure
  const structureResult = improveStructure(editedText);
  editedText = structureResult.text;
  allChanges.push(...structureResult.changes);

  // 5. Generate headline suggestions
  const generators = HEADLINE_TEMPLATES[tone] ?? HEADLINE_TEMPLATES.professional;
  const headlineSuggestions = generators.map((gen) => gen(topic));

  // Pick the best headline as the edited title
  const editedTitle = headlineSuggestions[0];
  if (editedTitle !== title) {
    allChanges.push({
      type: "headline",
      original: title,
      replacement: editedTitle,
      reason: "Suggested a more engaging headline that better captures reader interest",
    });
  }

  // 6. Score
  const qualityScore = scoreArticle(editedText, allChanges.length);

  return {
    editedArticle: editedText,
    editedTitle,
    headlineSuggestions,
    changes: allChanges,
    qualityScore,
  };
}
