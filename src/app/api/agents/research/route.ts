import { NextRequest, NextResponse } from "next/server";
import { getMessageBus } from "@/lib/message-bus";
import { ResearchAgent } from "@/agents";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const topic = body.topic;

    if (!topic || typeof topic !== "string" || topic.trim().length === 0) {
      return NextResponse.json(
        { error: "A non-empty 'topic' string is required in the request body" },
        { status: 400 }
      );
    }

    const bus = getMessageBus();
    bus.clear();
    const agent = new ResearchAgent(bus);

    const result = await agent.research(topic.trim());

    return NextResponse.json(result);
  } catch (error) {
    console.error("Research agent error:", error);
    return NextResponse.json(
      {
        error: error instanceof Error ? error.message : "Research failed",
      },
      { status: 500 }
    );
  }
}

export async function GET() {
  return NextResponse.json({
    agent: "research",
    description:
      "Searches the web for a given topic and returns 5-7 key facts with sources",
    usage: {
      method: "POST",
      body: { topic: "string (required)" },
    },
    response: {
      topic: "string",
      summary: "string",
      facts: [
        {
          fact: "A factual statement extracted from search results",
          sourceUrl: "https://...",
          sourceTitle: "Title of the source page",
        },
      ],
      sources: [
        {
          title: "string",
          url: "string",
          snippet: "string",
          retrievedAt: "ISO 8601 timestamp",
        },
      ],
      searchQueries: ["array of queries used"],
      completedAt: "ISO 8601 timestamp",
    },
  });
}
