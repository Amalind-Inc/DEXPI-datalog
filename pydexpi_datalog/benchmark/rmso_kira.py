"""Checkpoint-aware Terminus-KIRA adapter for the RMSO Arm C runner.

The external KIRA dependency is imported lazily so the benchmark's normal
unit-test environment does not need Harbor installed.  The class builder is
the public behavior seam used by tests and by the lazily resolved live class.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

CHECKPOINT_FIELD = "rmso_checkpoint"
CHECKPOINT_VALUE = "accepted"
CHECKPOINT_PREFLIGHT_COMMAND = (
    "python3 /input/run_query.py /workspace/analysis.dl\n"
)
FINALIZATION_RESERVE_SEC = 60.0
PREFLIGHT_MAX_SEC = 50.0


def _accepted_checkpoint(output: str) -> bool:
    """Return whether bounded terminal output contains the helper's receipt."""
    for line in output.splitlines():
        try:
            receipt = json.loads(line.strip())
        except (ValueError, TypeError):
            continue
        if (
            isinstance(receipt, dict)
            and receipt.get("ok") is True
            and receipt.get(CHECKPOINT_FIELD) == CHECKPOINT_VALUE
        ):
            return True
    return False


def build_checkpoint_kira_class(
    base_class: type,
    response_type: type,
    command_type: type,
) -> type:
    """Build an agent that treats a valid executed checkpoint as terminal."""

    class CheckpointTerminusKira(base_class):
        def __init__(
            self,
            *args: Any,
            checkpoint_cutoff_sec: float = 240.0,
            checkpoint_preflight_command: str = CHECKPOINT_PREFLIGHT_COMMAND,
            **kwargs: Any,
        ) -> None:
            super().__init__(*args, **kwargs)
            self._rmso_checkpoint_ready = False
            self._rmso_started_at: float | None = None
            self._rmso_checkpoint_cutoff_sec = checkpoint_cutoff_sec
            # Normalize so callers may pass the command without a trailing
            # newline (e.g. through Harbor's --agent-kwarg CLI plumbing).
            self._rmso_preflight_command = (
                checkpoint_preflight_command
                if checkpoint_preflight_command.endswith("\n")
                else checkpoint_preflight_command + "\n"
            )

        async def run(self, *args: Any, **kwargs: Any) -> Any:
            # Start the reserve clock at the agent phase, not while Harbor is
            # still constructing the Docker environment.
            self._rmso_started_at = time.monotonic()
            return await super().run(*args, **kwargs)

        async def _execute_commands(self, commands: Any, session: Any) -> Any:
            return await self.execute_checkpoint_commands(commands, session)

        async def execute_checkpoint_commands(
            self, commands: Any, session: Any
        ) -> Any:
            """Execute a KIRA command batch and arm only a replayed checkpoint."""
            outputs: list[str] = []
            executed_model_commands: list[Any] = []
            cutoff_reached = False
            candidate_seen = False

            # KIRA normally executes a whole model-supplied batch before the
            # caller can inspect output. Execute one command at a time so the
            # first successful helper receipt prevents commands 2..N from
            # consuming time or mutating the accepted program.
            for command in commands:
                remaining = self._rmso_exploration_remaining()
                if remaining <= 0:
                    cutoff_reached = True
                    break
                try:
                    executed_model_commands.append(command)
                    result = await asyncio.wait_for(
                        super()._execute_commands([command], session),
                        timeout=remaining,
                    )
                except TimeoutError:
                    await self._rmso_interrupt(session)
                    cutoff_reached = True
                    break
                outputs.append(result[1])
                if not result[0] and _accepted_checkpoint(result[1]):
                    candidate_seen = True
                    break

            if not commands and self._rmso_exploration_remaining() <= 0:
                cutoff_reached = True

            # Never trust model-visible stdout as the terminal condition. At a
            # candidate receipt—or when exploration time expires—spend only the
            # reserved tail on one fixed replay of the current analysis.
            if candidate_seen or cutoff_reached:
                self._rmso_checkpoint_ready = await self._rmso_preflight(session)
                outputs.append(
                    "RMSO mechanical preflight: "
                    + ("accepted" if self._rmso_checkpoint_ready else "rejected")
                )

            # KIRA records this same list after the method returns. Truncate it
            # so the persisted trajectory and post-run command budget describe
            # only model commands that were actually sent to the terminal.
            if isinstance(commands, list):
                commands[:] = executed_model_commands

            return cutoff_reached and not self._rmso_checkpoint_ready, "\n".join(
                outputs
            )

        async def _handle_llm_interaction(self, *args: Any, **kwargs: Any) -> Any:
            return await self.checkpoint_or_model_interaction(*args, **kwargs)

        async def checkpoint_or_model_interaction(
            self, *args: Any, **kwargs: Any
        ) -> Any:
            """Complete/cut off mechanically, or delegate one bounded model call."""
            if self._rmso_checkpoint_ready:
                return self._rmso_completion(
                    "Arm C executed checkpoint accepted; completing mechanically.",
                    "Executed checkpoint accepted.",
                )

            if self._rmso_started_at is None:
                self._rmso_started_at = time.monotonic()
            remaining = self._rmso_exploration_remaining()
            if remaining <= 0:
                await self.execute_checkpoint_commands([], self._session)
                if self._rmso_checkpoint_ready:
                    return self._rmso_completion(
                        "Arm C checkpoint accepted during finalization.",
                        "Latest executable checkpoint accepted at the cutoff.",
                    )
                return self._rmso_completion(
                    "Arm C finalization cutoff reached without a valid checkpoint.",
                    "No valid checkpoint existed at the finalization cutoff.",
                )
            try:
                return await asyncio.wait_for(
                    super()._handle_llm_interaction(*args, **kwargs),
                    timeout=remaining,
                )
            except TimeoutError:
                await self.execute_checkpoint_commands([], self._session)
                if self._rmso_checkpoint_ready:
                    return self._rmso_completion(
                        "Arm C checkpoint accepted during finalization.",
                        "Latest executable checkpoint accepted at the provider cutoff.",
                    )
                return self._rmso_completion(
                    "Arm C provider call reached the finalization cutoff.",
                    "No valid checkpoint existed before the provider cutoff.",
                )

        def _rmso_completion(self, content: str, analysis: str) -> Any:

            # Terminus-KIRA normally requires a second paid model call to confirm
            # task_complete.  The Arm C helper has already executed Souffle,
            # validated graph scope, and atomically persisted the answer, so the
            # runtime can satisfy that confirmation mechanically.
            self._rmso_checkpoint_ready = False
            self._pending_completion = True
            response = response_type(
                content=content,
                reasoning_content=None,
                usage=None,
            )
            return (
                [],
                True,
                "",
                analysis,
                "Complete without another model call.",
                response,
                None,
            )

        def _rmso_exploration_remaining(self) -> float:
            if self._rmso_started_at is None:
                self._rmso_started_at = time.monotonic()
            return self._rmso_checkpoint_cutoff_sec - (
                time.monotonic() - self._rmso_started_at
            )

        def _rmso_finalization_remaining(self) -> float:
            return self._rmso_exploration_remaining() + FINALIZATION_RESERVE_SEC

        async def _rmso_preflight(self, session: Any) -> bool:
            remaining = min(
                PREFLIGHT_MAX_SEC,
                self._rmso_finalization_remaining(),
            )
            if remaining <= 0:
                return False
            try:
                preflight = await asyncio.wait_for(
                    super()._execute_commands(
                        [
                            command_type(
                                keystrokes=self._rmso_preflight_command,
                                duration_sec=PREFLIGHT_MAX_SEC,
                            )
                        ],
                        session,
                    ),
                    timeout=remaining,
                )
            except TimeoutError:
                await self._rmso_interrupt(session)
                return False
            return not preflight[0] and _accepted_checkpoint(preflight[1])

        @staticmethod
        async def _rmso_interrupt(session: Any) -> None:
            await session.send_keys("C-c", block=False, min_timeout_sec=0.0)

    return CheckpointTerminusKira


def __getattr__(name: str) -> Any:
    if name != "CheckpointTerminusKira":
        raise AttributeError(name)
    from harbor.llms.base import LLMResponse
    from harbor.agents.terminus_2.terminus_2 import Command
    from terminus_kira.terminus_kira import TerminusKira

    return build_checkpoint_kira_class(TerminusKira, LLMResponse, Command)
