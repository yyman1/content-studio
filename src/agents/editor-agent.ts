import { BaseAgent } from "./base-agent";
import {
  AgentMessage,
  ArticleCitation,
  ArticleTone,
  EditorResult,
} from "./types";
import { MessageBus } from "@/lib/message-bus";
import { editArticle } from "@/lib/article-editor";

export interface EditInput {
  title: string;
  article: string;
  topic: string;
  tone?: ArticleTone;
  citations?: ArticleCitation[];
}

export class EditorAgent extends BaseAgent {
  constructor(bus: MessageBus) {
    super(
      {
        id: "editor",
        name: "Editor Agent",
        description:
          "Reviews a drafted article for clarity, grammar, and engagement, and suggests catchy headlines",
        capabilities: [
          "grammar-check",
          "clarity-improvement",
          "redundancy-removal",
          "headline-generation",
          "quality-scoring",
        ],
      },
      bus
    );
  }

  protected async process(message: AgentMessage): Promise<AgentMessage> {
    const payload = message.payload as unknown as EditInput;
    const result = this.edit(payload);

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
  edit(input: EditInput): EditorResult {
    const {
      title,
      article,
      topic,
      tone = "professional",
      citations = [],
    } = input;

    if (!article || article.trim().length === 0) {
      throw new Error("A non-empty 'article' string is required for editing");
    }

    const result = editArticle({ article, title, topic, tone });

    return {
      originalTitle: title,
      editedTitle: result.editedTitle,
      headlineSuggestions: result.headlineSuggestions,
      originalArticle: article,
      editedArticle: result.editedArticle,
      changes: result.changes,
      qualityScore: result.qualityScore,
      wordCount: result.editedArticle.split(/\s+/).length,
      topic,
      tone,
      citations,
      editedAt: new Date().toISOString(),
    };
  }
}
