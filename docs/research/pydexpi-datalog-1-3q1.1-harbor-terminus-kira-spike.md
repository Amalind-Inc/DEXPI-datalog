# Harbor / Terminus-KIRA integration spike — `pydexpi-datalog-1-3q1.1`

**Recommendation: GO.** Harbor plus the released Terminus-KIRA agent is a viable
primary harness for the benchmark's agentic arms. The repository now includes a
replayable Docker-backed smoke episode that used the real Harbor CLI and the
unmodified released KIRA agent against a local OpenAI-compatible scripted model.
It passed Harbor's independent verifier with a structured verdict and canonical
witness IDs. The next implementation must still add the benchmark-specific
adapter and budget enforcement described in [follow-up constraints](#follow-up-constraints).

## Scope and evidence

This spike tests harness fit and structured submission, not answer quality. It
uses a deliberately tiny toy drawing and gives the expected JSON in the task
instruction; therefore it demonstrates serialization, native-tool use, and
verification rather than P&ID reasoning.

```json
{"verdict":"violation_found","witness_ids":["P-101","CV-201"]}
```

The source fixture and replay driver are committed under
`spikes/terminus_kira_hello_world/`. The driver starts a local stand-in rather
than a credentialed model, so it neither reads nor logs a BYOK secret.

### Observed run

| Check | Result |
| --- | --- |
| Harbor task with `nop` agent (red) | Reward `0.0`: the independent verifier rejected the absent structured answer. |
| Released KIRA with scripted OpenAI-compatible stand-in (green) | Reward `1.0`, no trial errors. |
| Native-tool model calls | Exactly 3: one `execute_commands`, then KIRA's two `task_complete` calls. |
| Structured result | Harbor verifier accepted the exact verdict and witness list. |
| Source preservation | The Docker task runs as an unprivileged user. Input lives in a root-owned, mode-`0555` directory with a root-owned, mode-`0444` drawing; the independent verifier also rejects changed drawing content. |
| Sandbox | Agent terminal ran in Harbor's Docker task environment. |

Reproduce the green run after checking out the official KIRA repository:

```sh
git clone https://github.com/krafton-ai/KIRA.git /tmp/terminus-kira
python3 spikes/terminus_kira_hello_world/run_scripted_episode.py \
  --kira-dir /tmp/terminus-kira \
  --jobs-dir /tmp/pydexpi-3q1-kira-green
```

The intentional red check is independently reproducible with:

```sh
uv run --directory /tmp/terminus-kira harbor run \
  --path "$PWD/spikes/terminus_kira_hello_world/tasks" \
  --agent nop --env docker --jobs-dir /tmp/pydexpi-3q1-kira-red
```

Prerequisites are Docker, `uv`, and Python 3. The run intentionally uses no
external model credential. `--jobs-dir` preserves Harbor's normal trajectory
and verifier artifacts for audit.

## Primary-source findings

### Task format and sandbox model

Harbor's own task tutorial defines a local task as an `instruction.md`,
`task.toml`, Docker `environment/`, and `tests/` verifier. Its `harbor run -p`
path uses the Docker environment for the agent and runs the verifier separately.
The smoke task follows that format: the input lives under `/input`, a root-owned
mode-`0555` directory, with the drawing root-owned and mode `0444`. The terminal
runs as an unprivileged user and writes only to `/workspace`. The verifier
independently validates unchanged input content and the agent-written
`/workspace/structured_answer.json`.

* [Harbor task tutorial — task layout and Docker environment](https://github.com/harbor-framework/harbor/blob/98ce2fef49071cdb2c30b6f13867ac18a11cdcf1/docs/content/docs/tasks/task-tutorial.mdx#L18-L93)
* [Harbor task tutorial — independent verifier and reward file](https://github.com/harbor-framework/harbor/blob/98ce2fef49071cdb2c30b6f13867ac18a11cdcf1/docs/content/docs/tasks/task-tutorial.mdx#L143-L170)

This matches DAR's description: Harbor orchestrates the runs, while
Terminus-2 lets the model inspect task materials autonomously via an interactive
`tmux` session in a sandbox. DAR describes KIRA as the Terminus-2 variant aimed
at premature submission and poor self-evaluation.

* [DAR §3.3 — Harbor, Terminus-2, and Terminus-KIRA](https://arxiv.org/html/2606.05009#S3.SS3)

### Model endpoints and structured calls

KIRA calls LiteLLM's asynchronous completion API with its `tools` schema. The
agent inherits Terminus-2's `api_base` configuration, which is passed through
to LiteLLM. The smoke replay exercised that path with
`openai/scripted-structured-answer` and a local HTTP server implementing
`/v1/chat/completions`; each request contained the native tool schema and the
three scripted responses were accepted by the released agent.

* [KIRA native tool schema](https://github.com/krafton-ai/KIRA/blob/652dacbf14d29ea93a83c496ee91e0e5ba286721/terminus_kira/terminus_kira.py#L137-L211)
* [KIRA's LiteLLM completion and `api_base` forwarding](https://github.com/krafton-ai/KIRA/blob/652dacbf14d29ea93a83c496ee91e0e5ba286721/terminus_kira/terminus_kira.py#L598-L658)
* [Terminus-2 `api_base` and `max_turns` constructor parameters](https://github.com/harbor-framework/harbor/blob/98ce2fef49071cdb2c30b6f13867ac18a11cdcf1/src/harbor/agents/terminus_2/terminus_2.py#L156-L187)

The harness itself supplies terminal-action and completion tools, not the
benchmark's `StructuredAnswer` domain type. The smoke task therefore uses the
standard Harbor boundary: the agent writes a JSON result in its task workspace,
and the independent verifier validates the exact object. This is the viable
mapping for the benchmark: task verifier/output artifact -> benchmark adapter
-> `StructuredAnswer`.

### Submission gate and limits

KIRA's `task_complete` tool does not finish immediately. On the first call it
injects a completion checklist; only a second completion call returns from the
agent loop. The replay records both calls in its Harbor trajectory. This is an
execution-time submission gate, not a human confirmation gate.

* [KIRA completion checklist](https://github.com/krafton-ai/KIRA/blob/652dacbf14d29ea93a83c496ee91e0e5ba286721/terminus_kira/terminus_kira.py#L320-L335)
* [KIRA's two-call completion handling](https://github.com/krafton-ai/KIRA/blob/652dacbf14d29ea93a83c496ee91e0e5ba286721/terminus_kira/terminus_kira.py#L1090-L1184)

A per-episode limit is available as the `max_turns` agent argument; task and
verifier time limits are available in `task.toml`. That is sufficient to make
round and wall-time budgets explicit in Arm A's integration. **There is not an
upstream per-command-count budget:** a single `execute_commands` tool call can
contain an array of shell commands. The benchmark adapter must therefore record
command batches and enforce its equal tool budget explicitly (by wrapper or
post-run rejection); it must not claim KIRA enforces it natively.

## Follow-up integration notes

Ticket `pydexpi-datalog-1-3q1.8` can use these findings, subject to reconciling
its own acceptance criteria:

1. Generate a Harbor task from one drawing bundle, mount it read-only, and have
   the verifier validate the final verdict and witness IDs against graph facts.
2. Map Harbor trajectory, verifier output, token/cost metrics, and final JSON
   into the benchmark's `StructuredAnswer` and per-episode report artifact.
3. Set and record `max_turns`, task timeout, and verifier timeout in every run.
   Add explicit command-batch/tool-budget accounting so the Arm A and Arm C
   budgets are genuinely equal.
4. Retain KIRA's automatic two-step completion check as harness behavior, but
   do **not** introduce a pre-execution human confirmation gate. Programs and
   witnesses remain post-hoc audit artifacts, per the PRD amendment.
5. Use live Sonnet, GPT, and DeepSeek endpoints only in the later live matrix;
   this spike proves the OpenAI-compatible scripted-endpoint seam, not model
   quality or model-specific native-tool reliability.

## Decision

**GO — do not create the in-house fallback-loop ticket.** The required primary
harness path works against a scripted stand-in in a real Harbor Docker episode,
with native tool calls, terminal execution, a two-step submission gate, and an
independently verified structured answer. The only discovered limitation is
explicit command/tool-budget enforcement, which is a narrow requirement of the
future Arm A adapter rather than evidence that Harbor/KIRA cannot serve as its
primary harness.
