/**
 * THROWAWAY SPIKE — delete after recording the Pi integration verdict.
 *
 * Question: can pinned Pi create an in-memory PortLog session with only a
 * custom PortLog tool? This script creates an empty temporary auth store,
 * never prompts a model, and never reads ~/.pi/agent/auth.json.
 *
 * Run: npm run prototype:pi
 */
import os from "node:os";
import path from "node:path";
import { Type } from "typebox";
import {
  AuthStorage,
  createAgentSession,
  defineTool,
  SessionManager,
} from "@earendil-works/pi-coding-agent";

const probeRoot = path.join(os.tmpdir(), `portlog-pi-probe-${process.pid}`);
const inspectPidRegion = defineTool({
  name: "inspect_pid_region",
  label: "Inspect P&ID region",
  description: "Returns a deliberately synthetic inspection result for this spike.",
  parameters: Type.Object({ tag: Type.String() }),
  execute: async (_toolCallId, { tag }) => ({
    content: [{ type: "text", text: `Synthetic inspection for ${tag}` }],
    details: { tag, synthetic: true },
  }),
});
const { session } = await createAgentSession({
  agentDir: probeRoot,
  authStorage: AuthStorage.create(path.join(probeRoot, "auth.json")),
  sessionManager: SessionManager.inMemory(process.cwd()),
  noTools: "builtin",
  customTools: [inspectPidRegion],
  tools: ["inspect_pid_region"],
});

console.log(JSON.stringify({
  sessionFile: session.sessionFile,
  visibleTools: session.agent.state.tools.map((tool) => tool.name),
  modelPromptSent: false,
  credentialStore: "temporary-empty",
}, null, 2));

session.dispose();
