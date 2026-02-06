import { NextRequest, NextResponse } from "next/server";
import { getMessageBus } from "@/lib/message-bus";
import { ResearchAgent } from "@/agents/research-agent";
import { WriterAgent } from "@/agents/writer-agent";
import { EditorAgent } from "@/agents/editor-agent";
import type {
  ArticleTone,
  ResearchResult,
  WriterResult,
  EditorResult,
  OrchestrationStep,
  OrchestrationResult,
} from "@/agents/types";

const VALID_TONES: ArticleTone[] = [
  "professional",
  "casual",
  "academic",
  "journalistic",
];

// ── Helpers ──────────────────────────────────────────────────────────────

function makeStep(agent: string): OrchestrationStep {
  return { agent, status: "pending", durationMs: 0 };
}

async function runStep<T>(
  step: OrchestrationStep,
  fn: () => Promise<T> | T
): Promise<T> {
  step.status = "running";
  const start = performance.now();
  try {
    const result = await fn();
    step.durationMs = Math.round(performance.now() - start);
    step.status = "completed";
    return result;
  } catch (err) {
    step.durationMs = Math.round(performance.now() - start);
    step.status = "failed";
    step.error = err instanceof Error ? err.message : String(err);
    throw err;
  }
}

// ── POST handler ─────────────────────────────────────────────────────────

export async function POST(request: NextRequest) {
  const pipelineStart = performance.now();

  // Parse & validate input
  let topic: string;
  let tone: ArticleTone;
  try {
    const body = await request.json();
    topic = body.topic;
    tone = body.tone ?? "professional";

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

    topic = topic.trim();
  } catch {
    return NextResponse.json(
      { error: "Invalid JSON body" },
      { status: 400 }
    );
  }

  // Set up agents
  const bus = getMessageBus();
  bus.clear();
  const researchAgent = new ResearchAgent(bus);
  const writerAgent = new WriterAgent(bus);
  const editorAgent = new EditorAgent(bus);

  // Prepare step trackers
  const researchStep = makeStep("research");
  const writerStep = makeStep("writer");
  const editorStep = makeStep("editor");

  let researchData: ResearchResult | null = null;
  let writerData: WriterResult | null = null;
  let editorData: EditorResult | null = null;

  // ── Step 1: Research ─────────────────────────────────────────────────
  try {
    researchData = await runStep(researchStep, () =>
      researchAgent.research(topic)
    );
  } catch {
    // Research failed — mark remaining steps as skipped
    writerStep.status = "skipped";
    editorStep.status = "skipped";

    return NextResponse.json(
      buildResult("failed", topic, tone, pipelineStart, [researchStep, writerStep, editorStep], researchData, writerData, editorData),
      { status: 502 }
    );
  }

  // Validate research produced usable facts
  if (!researchData.facts || researchData.facts.length === 0) {
    researchStep.status = "completed"; // it ran fine, just no facts
    writerStep.status = "skipped";
    writerStep.error = "No facts available from research to write about";
    editorStep.status = "skipped";

    return NextResponse.json(
      buildResult("partial", topic, tone, pipelineStart, [researchStep, writerStep, editorStep], researchData, writerData, editorData),
      { status: 200 }
    );
  }

  // ── Step 2: Writer ───────────────────────────────────────────────────
  try {
    writerData = await runStep(writerStep, () =>
      writerAgent.write({
        topic: researchData!.topic,
        facts: researchData!.facts,
        sources: researchData!.sources,
        tone,
      })
    );
  } catch {
    editorStep.status = "skipped";

    return NextResponse.json(
      buildResult("partial", topic, tone, pipelineStart, [researchStep, writerStep, editorStep], researchData, writerData, editorData),
      { status: 200 }
    );
  }

  // ── Step 3: Editor ───────────────────────────────────────────────────
  try {
    editorData = await runStep(editorStep, () =>
      editorAgent.edit({
        title: writerData!.title,
        article: writerData!.article,
        topic: writerData!.topic,
        tone,
        citations: writerData!.citations,
      })
    );
  } catch {
    return NextResponse.json(
      buildResult("partial", topic, tone, pipelineStart, [researchStep, writerStep, editorStep], researchData, writerData, editorData),
      { status: 200 }
    );
  }

  // ── All steps succeeded ──────────────────────────────────────────────
  return NextResponse.json(
    buildResult("completed", topic, tone, pipelineStart, [researchStep, writerStep, editorStep], researchData, writerData, editorData)
  );
}

// ── Build the response ───────────────────────────────────────────────────

function buildResult(
  status: OrchestrationResult["status"],
  topic: string,
  tone: ArticleTone,
  pipelineStart: number,
  steps: OrchestrationStep[],
  research: ResearchResult | null,
  article: WriterResult | null,
  edited: EditorResult | null
): OrchestrationResult {
  return {
    status,
    topic,
    tone,
    steps,
    totalDurationMs: Math.round(performance.now() - pipelineStart),
    research,
    article,
    edited,
    completedAt: new Date().toISOString(),
  };
}

// ── GET handler ──────────────────────────────────────────────────────────

export async function GET() {
  return NextResponse.json({
    endpoint: "/api/orchestrate",
    description:
      "Runs the full content pipeline: Research → Writer → Editor. Each step feeds its typed output to the next. Includes per-step timing, status tracking, and graceful partial results on failure.",
    usage: {
      method: "POST",
      body: {
        topic: "string (required) — the subject to research and write about",
        tone: '(optional) "professional" | "casual" | "academic" | "journalistic" — defaults to "professional"',
      },
    },
    response: {
      status: '"completed" | "partial" | "failed"',
      topic: "string",
      tone: "string",
      steps: [
        {
          agent: "string — agent name",
          status: '"pending" | "running" | "completed" | "failed" | "skipped"',
          durationMs: "number — milliseconds this step took",
          error: "string | undefined — error message if failed",
        },
      ],
      totalDurationMs: "number — total pipeline duration in milliseconds",
      research:
        "ResearchResult | null — facts, sources, search queries (null if step failed)",
      article:
        "WriterResult | null — title, article body, citations (null if step failed/skipped)",
      edited:
        "EditorResult | null — edited article, changes, quality score, headline suggestions (null if step failed/skipped)",
      completedAt: "ISO 8601 timestamp",
    },
    agents: [
      {
        name: "Research Agent",
        description: "Searches the web and extracts 5-7 key facts with sources",
      },
      {
        name: "Writer Agent",
        description: "Composes a ~300-word article with inline citations",
      },
      {
        name: "Editor Agent",
        description: "Improves clarity, grammar, and suggests catchy headlines",
      },
    ],
  });
}
