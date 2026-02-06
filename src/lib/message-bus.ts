import { AgentMessage, MessageHandler } from "@/agents/types";

type Subscriber = {
  agentId: string;
  handler: MessageHandler;
};

export class MessageBus {
  private subscribers: Map<string, Subscriber> = new Map();
  private messageLog: AgentMessage[] = [];

  subscribe(agentId: string, handler: MessageHandler): void {
    this.subscribers.set(agentId, { agentId, handler });
  }

  unsubscribe(agentId: string): void {
    this.subscribers.delete(agentId);
  }

  async send(message: AgentMessage): Promise<AgentMessage | void> {
    this.messageLog.push(message);

    if (message.type === "broadcast") {
      const results = await Promise.all(
        Array.from(this.subscribers.values())
          .filter((sub) => sub.agentId !== message.from)
          .map((sub) => sub.handler(message))
      );
      return results.find((r) => r !== undefined);
    }

    const target = this.subscribers.get(message.to);
    if (!target) {
      throw new Error(`Agent "${message.to}" not found on the message bus`);
    }

    return target.handler(message);
  }

  getLog(): AgentMessage[] {
    return [...this.messageLog];
  }

  clear(): void {
    this.messageLog = [];
  }
}

let busInstance: MessageBus | null = null;

export function getMessageBus(): MessageBus {
  if (!busInstance) {
    busInstance = new MessageBus();
  }
  return busInstance;
}
