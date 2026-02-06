export interface AgentMessage {
  id: string;
  from: string;
  to: string;
  type: "request" | "response" | "broadcast";
  payload: Record<string, unknown>;
  timestamp: number;
  correlationId?: string;
}

export interface AgentConfig {
  id: string;
  name: string;
  description: string;
  capabilities: string[];
}

export type MessageHandler = (message: AgentMessage) => Promise<AgentMessage | void>;

export interface AgentStatus {
  id: string;
  name: string;
  state: "idle" | "processing" | "error";
  lastMessage?: AgentMessage;
}

export interface PipelineStep {
  agentId: string;
  input: Record<string, unknown>;
  output?: Record<string, unknown>;
  status: "pending" | "running" | "completed" | "error";
  error?: string;
}

export interface PipelineResult {
  steps: PipelineStep[];
  finalOutput: Record<string, unknown>;
}

export interface ResearchFact {
  fact: string;
  sourceUrl: string;
  sourceTitle: string;
}

export interface ResearchSource {
  title: string;
  url: string;
  snippet: string;
  retrievedAt: string;
}

export interface ResearchResult {
  topic: string;
  summary: string;
  facts: ResearchFact[];
  sources: ResearchSource[];
  searchQueries: string[];
  completedAt: string;
}

export type ArticleTone = "professional" | "casual" | "academic" | "journalistic";

export interface ArticleCitation {
  index: number;
  sourceTitle: string;
  sourceUrl: string;
}

export interface WriterResult {
  title: string;
  article: string;
  tone: ArticleTone;
  wordCount: number;
  citations: ArticleCitation[];
  topic: string;
  generatedAt: string;
}

export interface EditChange {
  type: "grammar" | "clarity" | "redundancy" | "headline" | "structure";
  original: string;
  replacement: string;
  reason: string;
}

export interface QualityScore {
  overall: number;
  grammar: number;
  clarity: number;
  structure: number;
  engagement: number;
}

export interface EditorResult {
  originalTitle: string;
  editedTitle: string;
  headlineSuggestions: string[];
  originalArticle: string;
  editedArticle: string;
  changes: EditChange[];
  qualityScore: QualityScore;
  wordCount: number;
  topic: string;
  tone: ArticleTone;
  citations: ArticleCitation[];
  editedAt: string;
}

export type OrchestrationStepStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "skipped";

export interface OrchestrationStep {
  agent: string;
  status: OrchestrationStepStatus;
  durationMs: number;
  error?: string;
}

export interface OrchestrationResult {
  status: "completed" | "partial" | "failed";
  topic: string;
  tone: ArticleTone;
  steps: OrchestrationStep[];
  totalDurationMs: number;
  research: ResearchResult | null;
  article: WriterResult | null;
  edited: EditorResult | null;
  completedAt: string;
}
