export type PortLogEvent =
  | { type: "assistant_text_delta"; turnId: string; text: string }
  | { type: "inspection_started"; turnId: string; capability: string }
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

export interface PiSessionFactory {
  createSession(): Promise<PiSession>;
}

/**
 * Translates a Pi invocation into PortLog events without allowing Pi session
 * persistence to become PortLog's visible chat or turn record.
 */
export class PiPortLogAgentAdapter {
  private readonly factory: PiSessionFactory;

  constructor(factory: PiSessionFactory) {
    this.factory = factory;
  }

  async *startTurn(input: PortLogTurnInput): AsyncIterable<PortLogEvent> {
    const session = await this.factory.createSession();
    if (session.sessionFile !== undefined) {
      session.dispose();
      throw new Error("PortLog requires an in-memory Pi session");
    }

    const events: PortLogEvent[] = [];
    const unsubscribe = session.subscribe((event) => {
      if (event.type === "text") {
        events.push({ type: "assistant_text_delta", turnId: input.turnId, text: event.text });
      }
      if (event.type === "tool_start") {
        events.push({ type: "inspection_started", turnId: input.turnId, capability: event.name });
      }
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
