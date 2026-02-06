import { NextRequest, NextResponse } from "next/server";
import { getMessageBus } from "@/lib/message-bus";
import {
  AgentRegistry,
  ResearchAgent,
  WriterAgent,
  EditorAgent,
} from "@/agents";

function createPipeline(): AgentRegistry {
  const bus = getMessageBus();
  bus.clear();

  const registry = new AgentRegistry();
  registry.register(new ResearchAgent(bus));
  registry.register(new WriterAgent(bus));
  registry.register(new EditorAgent(bus));

  return registry;
}

export async function POST(request: NextRequest) {
  try {
    const { topic } = await request.json();

    if (!topic || typeof topic !== "string") {
      return NextResponse.json(
        { error: "A 'topic' string is required" },
        { status: 400 }
      );
    }

    const registry = createPipeline();

    const result = await registry.runPipeline(
      ["research", "writer", "editor"],
      { topic }
    );

    return NextResponse.json(result);
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Pipeline failed" },
      { status: 500 }
    );
  }
}

export async function GET() {
  const bus = getMessageBus();
  const registry = new AgentRegistry();
  registry.register(new ResearchAgent(bus));
  registry.register(new WriterAgent(bus));
  registry.register(new EditorAgent(bus));

  const agents = registry.getAll().map((agent) => ({
    ...agent.config,
    status: agent.getStatus(),
  }));

  return NextResponse.json({ agents });
}
