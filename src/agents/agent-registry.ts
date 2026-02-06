import { BaseAgent } from "./base-agent";
import { PipelineResult, PipelineStep } from "./types";

export class AgentRegistry {
  private agents: Map<string, BaseAgent> = new Map();

  register(agent: BaseAgent): void {
    this.agents.set(agent.config.id, agent);
  }

  get(id: string): BaseAgent | undefined {
    return this.agents.get(id);
  }

  getAll(): BaseAgent[] {
    return Array.from(this.agents.values());
  }

  unregister(id: string): void {
    const agent = this.agents.get(id);
    if (agent) {
      agent.destroy();
      this.agents.delete(id);
    }
  }

  async runPipeline(
    agentIds: string[],
    initialInput: Record<string, unknown>
  ): Promise<PipelineResult> {
    const steps: PipelineStep[] = agentIds.map((id) => ({
      agentId: id,
      input: {},
      status: "pending" as const,
    }));

    let currentInput = initialInput;

    for (let i = 0; i < agentIds.length; i++) {
      const agentId = agentIds[i];
      const agent = this.agents.get(agentId);

      if (!agent) {
        steps[i].status = "error";
        steps[i].error = `Agent "${agentId}" not found`;
        return { steps, finalOutput: currentInput };
      }

      steps[i].input = currentInput;
      steps[i].status = "running";

      try {
        const previousAgentId = i > 0 ? agentIds[i - 1] : "pipeline";
        const response = await agent.sendTo(agentId, {
          ...currentInput,
          _from: previousAgentId,
        });

        const output = response?.payload ?? currentInput;
        steps[i].output = output;
        steps[i].status = "completed";
        currentInput = output;
      } catch (error) {
        steps[i].status = "error";
        steps[i].error = error instanceof Error ? error.message : String(error);
        return { steps, finalOutput: currentInput };
      }
    }

    return { steps, finalOutput: currentInput };
  }
}
