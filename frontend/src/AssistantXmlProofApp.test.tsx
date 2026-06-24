import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { AssistantXmlProofApp } from "./AssistantXmlProofApp";

describe("AssistantXmlProofApp", () => {
  it("routes XML upload through app-owned prepare logic and opens app-owned topology state", async () => {
    const user = userEvent.setup();
    const calls: Array<{ url: string; method?: string; body?: unknown }> = [];
    const fetchImpl = async (input: RequestInfo | URL, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(init.body.toString()) : undefined;
      calls.push({ url: input.toString(), method: init?.method, body });
      return jsonResponse({
        status: "ready",
        topology: {
          nodes: [
            { id: "pump-101", label: "P-101", kind: "Pump" },
            { id: "valve-102", label: "V-102", kind: "Valve" },
          ],
          edges: [{ id: "edge-1", source: "pump-101", target: "valve-102", label: "feeds" }],
        },
      });
    };

    render(<AssistantXmlProofApp fetchImpl={fetchImpl} sessionId="proof-a" />);

    await user.upload(
      screen.getByLabelText(/attach dexpi xml/i),
      new File(["<PlantModel />"], "plant.xml", { type: "text/xml" }),
    );

    expect(await screen.findByText(/uploaded plant.xml/i)).toBeInTheDocument();
    expect(await screen.findByText(/topology ready/i)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /app-owned topology/i })).toHaveTextContent("P-101");
    expect(screen.getByRole("region", { name: /app-owned topology/i })).toHaveTextContent("V-102");
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({
      url: "/api/review/sessions/proof-a/prepare",
      method: "POST",
      body: { filename: "plant.xml", content: "<PlantModel />" },
    });
  });

  it("shows a recoverable chat error when prepare fails instead of staying in processing", async () => {
    const user = userEvent.setup();
    const fetchImpl = async () => jsonResponse({ error: { message: "bad xml" } }, 500);

    render(<AssistantXmlProofApp fetchImpl={fetchImpl} sessionId="proof-b" />);

    await user.upload(
      screen.getByLabelText(/attach dexpi xml/i),
      new File(["<broken"], "bad.xml", { type: "text/xml" }),
    );

    expect(await screen.findByText(/upload failed/i)).toBeInTheDocument();
    expect(screen.getByText(/try another xml file/i)).toBeInTheDocument();
    expect(screen.queryByText(/processing bad.xml/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/attach dexpi xml/i)).toBeEnabled();
  });
});

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as Response);
}
