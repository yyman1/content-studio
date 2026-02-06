import { AgentConfig, AgentMessage, AgentStatus } from "./types";
import { MessageBus } from "@/lib/message-bus";

let idCounter = 0;
function generateId(): string {
  return `msg_${Date.now()}_${++idCounter}`;
}

export abstract class BaseAgent {
  readonly config: AgentConfig;
  private status: AgentStatus;
  protected bus: MessageBus;

  constructor(config: AgentConfig, bus: MessageBus) {
    this.config = config;
    this.bus = bus;
    this.status = {
      id: config.id,
      name: config.name,
      state: "idle",
    };

    this.bus.subscribe(config.id, this.handleMessage.bind(this));
  }

  private async handleMessage(message: AgentMessage): Promise<AgentMessage | void> {
    this.status.state = "processing";
    this.status.lastMessage = message;

    try {
      const result = await this.process(message);
      this.status.state = "idle";
      return result;
    } catch (error) {
      this.status.state = "error";
      throw error;
    }
  }

  protected abstract process(message: AgentMessage): Promise<AgentMessage | void>;

  protected createMessage(
    to: string,
    payload: Record<string, unknown>,
    type: AgentMessage["type"] = "request",
    correlationId?: string
  ): AgentMessage {
    return {
      id: generateId(),
      from: this.config.id,
      to,
      type,
      payload,
      timestamp: Date.now(),
      correlationId,
    };
  }

  async sendTo(to: string, payload: Record<string, unknown>): Promise<AgentMessage | void> {
    const message = this.createMessage(to, payload);
    return this.bus.send(message);
  }

  getStatus(): AgentStatus {
    return { ...this.status };
  }

  destroy(): void {
    this.bus.unsubscribe(this.config.id);
  }
}
