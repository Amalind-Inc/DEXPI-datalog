export const PORTLOG_CAPABILITY_TOOLS = [
  "inspect_pid_region",
  "query_graph",
  "run_validation",
  "propose_correction",
] as const;

export type PortLogCapabilityTool = (typeof PORTLOG_CAPABILITY_TOOLS)[number];

export type PortLogEvent =
  | { type: "assistant_text_delta"; turnId: string; text: string }
  | { type: "inspection_started"; turnId: string; capability: PortLogCapabilityTool }
  | { type: "turn_completed"; turnId: string };

export type PiEvent =
  | { type: "text"; text: string }
  | { type: "tool_start"; name: string };

export interface PiSession {
  /** Undefined is required for the in-memory adapter boundary. */
  sessionFile: string | undefined;
  subscribe(listener: (event: PiEvent) => void): () => void;
  prompt(text: string): Promise<void>;
  abort(): Promise<void>;
  dispose(): void;
}

export interface PortLogTurnInput {
  turnId: string;
  text: string;
}

export interface PiSessionOptions {
  noBuiltins: true;
  capabilityTools: readonly PortLogCapabilityTool[];
}

export interface PiSessionFactory {
  createSession(options: PiSessionOptions): Promise<PiSession>;
}

function isPortLogCapabilityTool(name: string): name is PortLogCapabilityTool {
  return PORTLOG_CAPABILITY_TOOLS.includes(name as PortLogCapabilityTool);
}

/**
 * Translates a Pi invocation into PortLog events without allowing Pi session
 * persistence or coding capabilities to become PortLog's visible turn record.
 */
export class PiPortLogAgentAdapter {
  private readonly factory: PiSessionFactory;

  constructor(factory: PiSessionFactory) {
    this.factory = factory;
  }

  async *startTurn(input: PortLogTurnInput): AsyncIterable<PortLogEvent> {
    const session = await this.factory.createSession({
      noBuiltins: true,
      capabilityTools: PORTLOG_CAPABILITY_TOOLS,
    });
    if (session.sessionFile !== undefined) {
      session.dispose();
      throw new Error("PortLog requires an in-memory Pi session");
    }

    const events: PortLogEvent[] = [];
    const unsubscribe = session.subscribe((event) => {
      if (event.type === "text") {
        events.push({ type: "assistant_text_delta", turnId: input.turnId, text: event.text });
        return;
      }
      if (!isPortLogCapabilityTool(event.name)) {
        throw new Error(`unsupported Pi tool: ${event.name}`);
      }
      events.push({ type: "inspection_started", turnId: input.turnId, capability: event.name });
    });

    try {
      await session.prompt(input.text);
      yield* events;
      yield { type: "turn_completed", turnId: input.turnId };
    } finally {
      unsubscribe();
      session.dispose();
    }
  }
}
