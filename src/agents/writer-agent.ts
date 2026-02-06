import { BaseAgent } from "./base-agent";
import {
  AgentMessage,
  ArticleTone,
  ResearchFact,
  ResearchSource,
  WriterResult,
} from "./types";
import { MessageBus } from "@/lib/message-bus";
import { composeArticle } from "@/lib/article-composer";

const DEFAULT_TONE: ArticleTone = "professional";
const TARGET_WORD_COUNT = 300;

export interface WriteInput {
  topic: string;
  facts: ResearchFact[];
  sources: ResearchSource[];
  tone?: ArticleTone;
}

export class WriterAgent extends BaseAgent {
  constructor(bus: MessageBus) {
    super(
      {
        id: "writer",
        name: "Writer Agent",
        description:
          "Generates a ~300-word article from research data, maintaining tone and citing sources",
        capabilities: [
          "article-generation",
          "tone-adaptation",
          "source-citation",
        ],
      },
      bus
    );
  }

  protected async process(message: AgentMessage): Promise<AgentMessage> {
    const payload = message.payload as unknown as WriteInput;
    const result = this.write(payload);

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
  write(input: WriteInput): WriterResult {
    const { topic, facts, sources, tone = DEFAULT_TONE } = input;

    if (!facts || facts.length === 0) {
      throw new Error("At least one research fact is required to write an article");
    }

    const composed = composeArticle({
      topic,
      facts,
      sources: sources ?? [],
      tone,
      targetWordCount: TARGET_WORD_COUNT,
    });

    return {
      title: composed.title,
      article: composed.article,
      tone,
      wordCount: composed.wordCount,
      citations: composed.citations,
      topic,
      generatedAt: new Date().toISOString(),
    };
  }
}
