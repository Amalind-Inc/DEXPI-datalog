import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ReviewApp } from "./App";

describe("ReviewApp", () => {
  it("drives the single-file review workflow through the backend API without exposing provider keys", async () => {
    const user = userEvent.setup();
    const calls: Array<{ url: string; body?: unknown }> = [];
    const fetchImpl = async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = input.toString();
      const body = init?.body ? JSON.parse(init.body.toString()) : undefined;
      calls.push({ url, body });

      if (url.endsWith("/prepare")) {
        return jsonResponse({
          status: "ready",
          topology: topologyModel,
          visible_source_scope: [],
          provider_settings: { provider: "openrouter", model: "openrouter/owl-alpha", configured: false },
        });
      }
      if (url.endsWith("/source-scope")) {
        return jsonResponse({ source_scope_ids: body.source_scope_ids });
      }
      if (url.endsWith("/provider-settings")) {
        return jsonResponse({ provider: body.provider, model: body.model, configured: true });
      }
      if (url.endsWith("/logic-requests/improve")) {
        return jsonResponse({
          improvement: {
            prompt: body.prompt,
            formal_restatement: "Find pump discharge evidence for the selected source scope.",
            source_scope_ids: ["pump-101"],
          },
        });
      }
      if (url.endsWith("/logic-requests/confirm")) {
        return jsonResponse({
          confirmation: {
            formal_restatement: "Find pump discharge evidence for the selected source scope.",
            generated_datalog: ".decl answer(x:symbol)",
          },
        });
      }
      if (url.endsWith("/logic-requests/execute")) {
        return jsonResponse({
          result: {
            status: "pass",
            answer: "Pump P-101 has deterministic discharge evidence.",
            evidence_highlights: [{ object_id: "pump-101", label: "P-101" }],
          },
        });
      }
      if (url.endsWith("/rule-pack-results")) {
        return jsonResponse({ rule_id: body.rule_id, status: "pass", evidence: ["P-101"] });
      }
      if (url.endsWith("/exports")) {
        return jsonResponse({ export_id: "export-1", status: "ready" });
      }
      return jsonResponse({}, 404);
    };

    render(<ReviewApp fetchImpl={fetchImpl} sessionId="session-a" />);

    const improveButton = screen.getByRole("button", { name: /improve/i });
    expect(improveButton).toBeDisabled();

    await user.upload(
      screen.getByLabelText(/dexpi xml file/i),
      new File(["<PlantModel />"], "pump.xml", { type: "text/xml" }),
    );

    expect(await screen.findByText("pump.xml")).toBeInTheDocument();
    expect(await screen.findAllByText("P-101")).not.toHaveLength(0);
    expect(screen.getAllByText("Pipe Segment PS-1")).not.toHaveLength(0);
    expect(screen.getByRole("textbox", { name: /logic request/i })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: /select p-101/i }));
    const scopePanel = screen.getByRole("region", { name: /source scope/i });
    expect(within(scopePanel).getByText("pump-101")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText(/provider/i), "openrouter");
    await user.clear(screen.getByLabelText(/model/i));
    await user.type(screen.getByLabelText(/model/i), "openrouter/owl-alpha");
    await user.type(screen.getByLabelText(/api key/i), "sk-or-test-secret");
    await user.click(screen.getByRole("button", { name: /save provider/i }));

    expect(screen.getByText(/openrouter \/ openrouter\/owl-alpha configured/i)).toBeInTheDocument();
    expect(screen.queryByText("sk-or-test-secret")).not.toBeInTheDocument();

    await user.type(
      screen.getByRole("textbox", { name: /logic request/i }),
      "Check the selected pump discharge.",
    );
    expect(improveButton).toBeEnabled();
    await user.click(improveButton);
    expect(await screen.findByText(/Find pump discharge evidence/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /confirm restatement/i }));
    expect(await screen.findByText(/generated datalog/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /run deterministic answer/i }));
    expect(await screen.findByText(/Pump P-101 has deterministic discharge evidence/i)).toBeInTheDocument();
    expect(screen.getByText(/highlighted: P-101/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /run selected rule pack/i }));
    expect(await screen.findByText(/rule pack pass/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /export session/i }));
    expect(await screen.findByText(/export-1 ready/i)).toBeInTheDocument();

    expect(calls.map((call) => call.url)).toContain("/api/review/sessions/session-a/prepare");
    expect(calls.find((call) => call.url.endsWith("/provider-settings"))?.body).toMatchObject({
      provider: "openrouter",
      model: "openrouter/owl-alpha",
      credential: "sk-or-test-secret",
    });
  });
});

const topologyModel = {
  nodes: [
    { id: "pump-101", label: "P-101", kind: "Pump" },
    { id: "pipe-segment-1", label: "Pipe Segment PS-1", kind: "PipingNetworkSegment" },
  ],
  edges: [{ id: "edge-1", source: "pump-101", target: "pipe-segment-1", label: "discharges-to" }],
};

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as Response);
}
