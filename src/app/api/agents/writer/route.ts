import { NextRequest, NextResponse } from "next/server";
import { getMessageBus } from "@/lib/message-bus";
import { WriterAgent } from "@/agents";
import type { ArticleTone, ResearchFact, ResearchSource } from "@/agents";

const VALID_TONES: ArticleTone[] = [
  "professional",
  "casual",
  "academic",
  "journalistic",
];

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    // Accept either the full ResearchResult shape or a manual facts/sources payload
    const topic: string | undefined = body.topic;
    const facts: ResearchFact[] | undefined = body.facts;
    const sources: ResearchSource[] | undefined = body.sources;
    const tone: ArticleTone = body.tone ?? "professional";

    if (!topic || typeof topic !== "string" || topic.trim().length === 0) {
      return NextResponse.json(
        { error: "A non-empty 'topic' string is required" },
        { status: 400 }
      );
    }

    if (!facts || !Array.isArray(facts) || facts.length === 0) {
      return NextResponse.json(
        {
          error:
            "A non-empty 'facts' array is required. Each fact needs: { fact, sourceUrl, sourceTitle }",
        },
        { status: 400 }
      );
    }

    if (!VALID_TONES.includes(tone)) {
      return NextResponse.json(
        { error: `Invalid tone. Must be one of: ${VALID_TONES.join(", ")}` },
        { status: 400 }
      );
    }

    const bus = getMessageBus();
    bus.clear();
    const agent = new WriterAgent(bus);

    const result = agent.write({
      topic: topic.trim(),
      facts,
      sources: sources ?? [],
      tone,
    });

    return NextResponse.json(result);
  } catch (error) {
    console.error("Writer agent error:", error);
    return NextResponse.json(
      {
        error: error instanceof Error ? error.message : "Article generation failed",
      },
      { status: 500 }
    );
  }
}

export async function GET() {
  return NextResponse.json({
    agent: "writer",
    description:
      "Generates a ~300-word article from research data, maintaining tone and citing sources",
    usage: {
      method: "POST",
      body: {
        topic: "string (required)",
        facts: [
          {
            fact: "string — a factual statement",
            sourceUrl: "string — URL of the source",
            sourceTitle: "string — title of the source",
          },
        ],
        sources:
          "(optional) array of { title, url, snippet, retrievedAt } for additional context",
        tone: '(optional) "professional" | "casual" | "academic" | "journalistic" — defaults to "professional"',
      },
    },
    tip: "You can pipe the output of POST /api/agents/research directly into this endpoint.",
    response: {
      title: "string",
      article: "string — full article text with inline [n] citations",
      tone: "string",
      wordCount: "number",
      citations: [
        { index: "number", sourceTitle: "string", sourceUrl: "string" },
      ],
      topic: "string",
      generatedAt: "ISO 8601 timestamp",
    },
  });
}
