# Chainlit OSS v1 Review Shell Spike

This spike evaluates Chainlit as the shell for the OSS v1 single-file P&ID
review workflow described by bead `pydexpi-datalog-1-37x.2`.

## Decision

Use Chainlit as a partial shell, not the primary OSS v1 product shell.

Chainlit is a good fit for a quick Python-native review workflow spike: it can
accept one uploaded DEXPI XML file, call the in-process
`ReviewSessionService`, show coarse job state, expose assistant actions, and
render a custom topology summary panel. It is not a good fit as the primary v1
application shell because the stock Chainlit web app is chat-centered, and its
built-in custom elements are `.jsx` snippets with a restricted import surface.
That conflicts with the PRD's typed React/TSX frontend requirement and the
expected graph-library topology review view.

The recommended architecture for implementation beads is:

1. Build the primary OSS v1 app as a repository-owned React/TypeScript frontend
   over a Python backend API.
2. Optionally use Chainlit for a narrow internal spike/demo shell while the
   backend workflow contracts are still stabilizing.
3. Reconsider Chainlit's `@chainlit/react-client` only if the team wants a
   custom React frontend that reuses Chainlit backend/session primitives. In
   that mode Chainlit is infrastructure, not the primary visible shell.

## Sources Reviewed

- Chainlit repository: `https://github.com/Chainlit/chainlit`
- Chainlit overview: `https://docs.chainlit.io/get-started/overview`
- File upload API: `https://docs.chainlit.io/api-reference/ask/ask-for-file`
- Task status UI: `https://docs.chainlit.io/api-reference/elements/tasklist`
- Action API: `https://docs.chainlit.io/concepts/action`
- Custom element API: `https://docs.chainlit.io/api-reference/elements/custom`
- Ask/custom confirmation flow: `https://docs.chainlit.io/advanced-features/ask-user`
- React client option: `https://docs.chainlit.io/deploy/react/overview`

## Fit Against Acceptance Criteria

| Criterion | Chainlit fit | Spike finding |
| --- | --- | --- |
| DEXPI upload can start a session-preparation job | Supported | `AskFileMessage` accepts one uploaded file, supports extension/MIME constraints, and exposes a server-local uploaded file path. A Chainlit handler can pass that path to `ReviewSessionService.start_preparation(...)`. |
| Chainlit shows coarse job status and optional stage text | Supported | `TaskList` has a top-level status plus task statuses. It can represent queued, running, succeeded, and failed preparation stages using the existing job `stage_history`. |
| Chainlit can host or embed a custom topology panel | Partially supported | `CustomElement` can render a JSX component inline, side, or page and can receive Python-provided props. It can show a topology summary and selection callbacks. It is not enough for the primary topology review view because custom elements are JSX-only and allowed imports do not include graph libraries such as Cytoscape.js. |
| Chainlit actions can support Improve, confirmation, and selected rule-pack execution | Supported | `Action` buttons can carry payloads and invoke Python callbacks. `AskActionMessage`/`AskElementMessage` can block for explicit confirmation. This is sufficient for Improve, Accept/Reject confirmation, and selected rule-pack execution. |
| Decision recorded | Complete | Decision is `Chainlit partial shell`. |

## Minimal Spike Shape

The smallest Chainlit demo worth building in a follow-up implementation bead is:

```python
import chainlit as cl
from pathlib import Path

from pydexpi_datalog.workflow.review_session import ReviewSessionService


service = ReviewSessionService(artifact_root=Path(".tmp/chainlit-sessions"))


@cl.on_chat_start
async def start() -> None:
    files = await cl.AskFileMessage(
        content="Upload one DEXPI 1.3 XML file.",
        accept={"text/xml": [".xml"], "application/xml": [".xml"]},
        max_files=1,
    ).send()
    if not files:
        return

    task_list = cl.TaskList()
    task_list.status = "Running..."
    task = cl.Task(title="Preparing session", status=cl.TaskStatus.RUNNING)
    await task_list.add_task(task)
    await task_list.send()

    result = service.start_preparation(dexpi_xml_path=Path(files[0].path))

    task.status = (
        cl.TaskStatus.DONE
        if result["job"]["status"] == "succeeded"
        else cl.TaskStatus.FAILED
    )
    task.title = f"Session preparation: {result['job']['stage']}"
    task_list.status = result["job"]["status"]
    await task_list.send()

    if result["topology_view"]:
        topology = cl.CustomElement(
            name="TopologyPanel",
            props={"topology": result["topology_view"]},
            display="side",
        )
        await cl.Message(
            content="Session is ready.",
            elements=[topology],
            actions=[
                cl.Action(name="improve", label="Improve", payload={}),
                cl.Action(name="run_rule_pack", label="Run selected checks", payload={}),
            ],
        ).send()
```

This proves the session-preparation loop but intentionally avoids treating the
Chainlit stock UI as the final product surface.

## Product Risks

- Primary topology view risk: the OSS v1 product needs a dense process-topology
  workspace with pan, zoom, selection, evidence highlighting, and stable graph
  IDs. Chainlit custom elements can render a panel, but the stock shell does not
  naturally provide the center-pane/right-assistant layout described by the PRD.
- Frontend contract risk: Chainlit custom elements are not TSX components, so
  API response shapes and graph props would not get the same first-class type
  checking as a repository-owned TypeScript app.
- Graph library risk: the documented custom-element import allowlist excludes
  Cytoscape.js, which is the PRD's recommended graph visualization default.
- Maintenance risk: the Chainlit GitHub README says the project became
  community-maintained on May 1, 2025. That does not disqualify it, but it
  increases the cost of making it the core product shell.

## Implementation Guidance

- `pydexpi-datalog-1-37x.5` can use Chainlit to validate upload-to-ready
  orchestration if the goal is quick interaction around the Python workflow.
- `pydexpi-datalog-1-37x.6` and evidence-highlighting work should not depend on
  Chainlit custom elements as the long-term topology surface. They should target
  a typed topology-view model that a React/TSX graph component can consume.
- `pydexpi-datalog-1-37x.14` should record the architecture as "Python backend
  API plus React/TypeScript frontend; Chainlit is optional spike tooling or
  reusable backend/session infrastructure, not the primary shell."
