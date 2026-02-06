import { NextRequest, NextResponse } from "next/server";
import { getMessageBus } from "@/lib/message-bus";
import { EditorAgent } from "@/agents";
import type { ArticleCitation, ArticleTone } from "@/agents";

const VALID_TONES: ArticleTone[] = [
  "professional",
  "casual",
  "academic",
  "journalistic",
];

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    const title: string | undefined = body.title;
    const article: string | undefined = body.article;
    const topic: string | undefined = body.topic;
    const tone: ArticleTone = body.tone ?? "professional";
    const citations: ArticleCitation[] = body.citations ?? [];

    if (!article || typeof article !== "string" || article.trim().length === 0) {
      return NextResponse.json(
        { error: "A non-empty 'article' string is required" },
        { status: 400 }
      );
    }

    if (!topic || typeof topic !== "string" || topic.trim().length === 0) {
      return NextResponse.json(
        { error: "A non-empty 'topic' string is required" },
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
    const agent = new EditorAgent(bus);

    const result = agent.edit({
      title: title ?? "Untitled",
      article: article.trim(),
      topic: topic.trim(),
      tone,
      citations,
    });

    return NextResponse.json(result);
  } catch (error) {
    console.error("Editor agent error:", error);
    return NextResponse.json(
      {
        error: error instanceof Error ? error.message : "Editing failed",
      },
      { status: 500 }
    );
  }
}

export async function GET() {
  return NextResponse.json({
    agent: "editor",
    description:
      "Reviews a drafted article for clarity, grammar, and engagement, and suggests catchy headlines",
    usage: {
      method: "POST",
      body: {
        title: "string (optional, defaults to 'Untitled')",
        article: "string (required) — the article text to edit",
        topic: "string (required) — the article topic",
        tone: '(optional) "professional" | "casual" | "academic" | "journalistic" — defaults to "professional"',
        citations:
          "(optional) array of { index, sourceTitle, sourceUrl } passed through from the writer",
      },
    },
    tip: "You can pipe the output of POST /api/agents/writer directly into this endpoint.",
    response: {
      originalTitle: "string",
      editedTitle: "string — suggested improved headline",
      headlineSuggestions: ["string — 3 alternative headlines"],
      originalArticle: "string",
      editedArticle: "string — the improved article text",
      changes: [
        {
          type: "grammar | clarity | redundancy | headline | structure",
          original: "string",
          replacement: "string",
          reason: "string — explanation of the change",
        },
      ],
      qualityScore: {
        overall: "number (0-100)",
        grammar: "number",
        clarity: "number",
        structure: "number",
        engagement: "number",
      },
      wordCount: "number",
      topic: "string",
      tone: "string",
      citations: "array — passed through from input",
      editedAt: "ISO 8601 timestamp",
    },
  });
}
