from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Callable
from contextlib import contextmanager
from threading import RLock
from dataclasses import dataclass
from pathlib import Path

from ..export.pipeline import export_graph_facts_artifact_timed
from ..semantics.derive_graph_semantics import (
    PROCESS_PIPING_ATTR_NAMES,
    TOPOLOGY_ATTR_NAMES,
    build_derived_graph_semantics_datalog,
    build_graph_facts_datalog,
)
from .artifact_store import ArtifactNotFound, ArtifactStore
from .geometry_gate import evaluate_geometry_gate
from .pid_view import build_pid_view
from .schematic_scene import build_schematic_scene_report, has_drawable_geometry
from .source_preparation_cache import SourcePreparationCache
from .topology_naming import derive_display_names


@dataclass(frozen=True)
class PreparationLimits:
    """Configurable boundaries for preparing a single DEXPI source.

    Defaults accept every bundled DEXPI 1.3 example P&ID; individual limits can
    be lowered to enforce stricter operational policy.
    """

    max_upload_bytes: int = 5_000_000
    max_xml_elements: int = 50_000
    max_xml_depth: int = 64
    max_preparation_seconds: float = 30.0
    max_graph_nodes: int = 5_000
    max_graph_edges: int = 10_000
    max_artifact_bytes: int = 50_000_000


def compute_source_id(dexpi_xml_path: Path) -> str:
    digest = hashlib.sha256(dexpi_xml_path.read_bytes()).hexdigest()[:16]
    return f"source-{digest}"


class ReviewSourceNotFound(ValueError):
    """A requested durable source record is not part of this review session."""


class SessionMutationCoordinator:
    """Serialize source-manifest mutations per session within this process.

    The coordinator protects callers sharing a Python process. Hosted
    deployments that permit multiple writer processes still need object-store
    conditional writes or a distributed lease; this class does not claim to
    solve that cross-process problem.
    """

    def __init__(self) -> None:
        self._registry_lock = RLock()
        self._locks: dict[str, tuple[RLock, int]] = {}

    @contextmanager
    def lock(self, session_id: str):
        with self._registry_lock:
            entry = self._locks.get(session_id)
            session_lock = entry[0] if entry is not None else RLock()
            self._locks[session_id] = (
                session_lock,
                (entry[1] if entry is not None else 0) + 1,
            )
        session_lock.acquire()
        try:
            yield
        finally:
            session_lock.release()
            with self._registry_lock:
                current = self._locks.get(session_id)
                if current is not None and current[0] is session_lock:
                    if current[1] <= 1:
                        del self._locks[session_id]
                    else:
                        self._locks[session_id] = (session_lock, current[1] - 1)


_SOURCE_MUTATIONS = SessionMutationCoordinator()


class ReviewSessionService:
    """Prepare uploaded DEXPI source files for a web review session."""

    def __init__(
        self,
        *,
        store: ArtifactStore,
        limits: PreparationLimits | None = None,
        clock: Callable[[], float] = time.perf_counter,
        mutation_coordinator: SessionMutationCoordinator | None = None,
    ) -> None:
        self.store = store
        self._limits = limits or PreparationLimits()
        self._clock = clock
        self._mutation_coordinator = mutation_coordinator or _SOURCE_MUTATIONS
        self._requests_by_session: dict[str, Path] = {}
        self._request_filename_by_session: dict[str, str] = {}

    def start_preparation(
        self,
        *,
        dexpi_xml_path: Path,
        session_id: str | None = None,
        source_filename: str | None = None,
    ) -> dict[str, object]:
        session_id = session_id or f"session-{uuid.uuid4().hex}"
        self._requests_by_session[session_id] = dexpi_xml_path
        self._request_filename_by_session[session_id] = (
            source_filename or dexpi_xml_path.name
        )
        return self._run_preparation(
            dexpi_xml_path=dexpi_xml_path,
            session_id=session_id,
            source_filename=self._request_filename_by_session[session_id],
            attempt=1,
        )

    def retry_preparation(self, *, session_id: str) -> dict[str, object]:
        dexpi_xml_path = self._requests_by_session.get(session_id)
        if dexpi_xml_path is None:
            return self._failed_result(
                session_id=session_id,
                attempt=1,
                diagnostics=[
                    diagnostic(
                        code="session.unknown",
                        message=f"No preparation request is known for session: {session_id}",
                    )
                ],
            )
        return self._run_preparation(
            dexpi_xml_path=dexpi_xml_path,
            session_id=session_id,
            source_filename=self._request_filename_by_session.get(
                session_id, dexpi_xml_path.name
            ),
            attempt=2,
        )

    def _run_preparation(
        self,
        *,
        dexpi_xml_path: Path,
        session_id: str,
        source_filename: str,
        attempt: int,
    ) -> dict[str, object]:
        with self._mutation_coordinator.lock(session_id):
            return self._run_preparation_unlocked(
                dexpi_xml_path=dexpi_xml_path,
                session_id=session_id,
                source_filename=source_filename,
                attempt=attempt,
            )

    def _run_preparation_unlocked(
        self,
        *,
        dexpi_xml_path: Path,
        session_id: str,
        source_filename: str,
        attempt: int,
    ) -> dict[str, object]:
        if not dexpi_xml_path.exists():
            return self._failed_result(
                session_id=session_id,
                attempt=attempt,
                diagnostics=[
                    diagnostic(
                        code="upload.missing_file",
                        message=(
                            "Uploaded DEXPI source file does not exist: "
                            f"{dexpi_xml_path}"
                        ),
                    )
                ],
            )

        content_source_id = compute_source_id(dexpi_xml_path)
        source_id = self._allocate_source_id(
            session_id=session_id,
            content_source_id=content_source_id,
        )

        validation_diagnostics = validate_upload_input(
            dexpi_xml_path, limits=self._limits
        )
        if validation_diagnostics:
            return self._failed_result(
                session_id=session_id,
                attempt=attempt,
                source_id=source_id,
                diagnostics=validation_diagnostics,
            )

        stage_history = [
            stage("queued", "queued"),
            stage("running", "validating upload"),
            stage("running", "extracting graph facts"),
        ]
        try:
            started_at = self._clock()
            phases_ms: dict[str, float] = {}
            source_cache = SourcePreparationCache(
                store=self.store,
                source_digest=content_source_id.removeprefix("source-"),
            )
            cache_hit = source_cache.available()
            if cache_hit:
                restored = source_cache.materialize(
                    session_id=session_id,
                    source_id=source_id,
                    source_path=str(dexpi_xml_path),
                )
                graph_facts = restored["graph_facts"]
                topology_view = restored["topology"]
                phases_ms["source_cache_materialize"] = (
                    self._clock() - started_at
                ) * 1000
            else:
                # The export pipeline writes graph_facts.json into a directory it
                # is handed, so preparation borrows a real one from the store.
                with self.store.local_dir(session_id) as session_dir:
                    export = export_graph_facts_artifact_timed(
                        dexpi_xml_path=dexpi_xml_path,
                        fixture_id=session_id,
                        output_dir=session_dir,
                        clock=self._clock,
                    )
                    graph_facts = export.artifact
                    phases_ms.update(export.phases_ms)

            graph_limit_diagnostics = check_graph_size_limits(
                graph=graph_facts["graph"], limits=self._limits
            )
            if graph_limit_diagnostics:
                return self._failed_result(
                    session_id=session_id,
                    attempt=attempt,
                    source_id=source_id,
                    diagnostics=graph_limit_diagnostics,
                )

            if not cache_hit:
                stage_history.append(
                    stage("running", "deriving graph facts datalog")
                )
                phase_started_at = self._clock()
                graph_facts_datalog = build_graph_facts_datalog(graph_facts)
                self.store.write_text(
                    f"{session_id}/graph_facts.dl", graph_facts_datalog
                )
                phases_ms["graph_datalog"] = (
                    self._clock() - phase_started_at
                ) * 1000
                stage_history.append(
                    stage("running", "deriving graph semantics")
                )
                phase_started_at = self._clock()
                derived_graph_semantics = build_derived_graph_semantics_datalog(
                    graph_facts
                )
                self.store.write_text(
                    f"{session_id}/derived_graph_semantics.dl",
                    derived_graph_semantics,
                )
                phases_ms["derived_semantics"] = (
                    self._clock() - phase_started_at
                ) * 1000
                stage_history.append(
                    stage("running", "building topology view model")
                )
                phase_started_at = self._clock()
                topology_view = build_topology_view_model(
                    graph_facts=graph_facts,
                    session_id=session_id,
                    source_id=source_id,
                    dexpi_xml_path=dexpi_xml_path,
                )
                phases_ms["topology_scene"] = (
                    self._clock() - phase_started_at
                ) * 1000
                source_cache.store(
                    graph_facts=graph_facts,
                    graph_facts_datalog=graph_facts_datalog,
                    derived_semantics_datalog=derived_graph_semantics,
                    topology=topology_view,
                )

            source_keys = source_artifact_keys(session_id, source_id)
            legacy_keys = session_artifact_keys(session_id)
            phase_started_at = self._clock()
            self.store.write_json(
                legacy_keys["topology_view_model"], topology_view
            )
            for kind in (
                "graph_facts_json",
                "graph_facts_datalog",
                "derived_graph_semantics_datalog",
            ):
                self.store.copy(legacy_keys[kind], source_keys[kind])

            artifact_paths = session_artifact_paths(
                self.store, session_id, source_id
            )
            readiness = {
                "state": "ready",
                "session_id": session_id,
                "source_id": source_id,
                "graph": graph_facts["graph"],
                "diagnostics": [],
                "topology_view_model_path": artifact_paths[
                    "topology_view_model"
                ],
            }
            self.store.write_json(
                source_keys["topology_view_model"], topology_view
            )
            self.store.write_json(source_keys["readiness_metadata"], readiness)
            phases_ms["topology_artifact_write"] = (
                self._clock() - phase_started_at
            ) * 1000

            elapsed_seconds = self._clock() - started_at
            time_limit_diagnostics = check_preparation_time_limit(
                elapsed_seconds=elapsed_seconds, limits=self._limits
            )
            if time_limit_diagnostics:
                self.store.delete_tree(source_artifact_prefix(session_id, source_id))
                return self._failed_result(
                    session_id=session_id,
                    attempt=attempt,
                    source_id=source_id,
                    diagnostics=time_limit_diagnostics,
                )

            artifact_limit_diagnostics = check_artifact_size_limits(
                store=self.store,
                session_id=session_id,
                source_id=source_id,
                limits=self._limits,
            )
            if artifact_limit_diagnostics:
                self.store.delete_tree(source_artifact_prefix(session_id, source_id))
                return self._failed_result(
                    session_id=session_id,
                    attempt=attempt,
                    source_id=source_id,
                    diagnostics=artifact_limit_diagnostics,
                )

            artifact_bytes = sum(
                self.store.size(key) for key in source_keys.values()
            )
            metrics = {
                "schema_version": 1,
                "total_ms": elapsed_seconds * 1000,
                "phases_ms": phases_ms,
                "counts": {
                    "upload_bytes": dexpi_xml_path.stat().st_size,
                    "graph_nodes": graph_facts["graph"]["node_count"],
                    "graph_edges": graph_facts["graph"]["edge_count"],
                    "topology_nodes": len(topology_view["nodes"]),
                    "topology_edges": len(topology_view["edges"]),
                    "topology_bytes": self.store.size(
                        source_keys["topology_view_model"]
                    ),
                    "artifact_bytes": artifact_bytes,
                },
            }

            self._record_ready_source(
                session_id=session_id,
                source_id=source_id,
                filename=source_filename,
            )
            stage_history.append(stage("succeeded", "ready"))

            return {
                "session_id": session_id,
                "source_id": source_id,
                "job": {
                    "job_id": f"{session_id}:prepare:{attempt}",
                    "kind": "session_preparation",
                    "status": "succeeded",
                    "stage": "ready",
                    "stage_history": stage_history,
                    "attempt": attempt,
                },
                "readiness": readiness,
                "topology_view": topology_view,
                "artifacts": artifact_paths,
                "metrics": metrics,
                "diagnostics": [],
            }
        except Exception as error:  # pyDEXPI has parser and conversion exceptions.
            self.store.delete_tree(source_artifact_prefix(session_id, source_id))
            return self._failed_result(
                session_id=session_id,
                attempt=attempt,
                source_id=source_id,
                diagnostics=[
                    diagnostic(
                        code="preparation.failed",
                        message=(
                            "Session preparation failed while extracting or "
                            "deriving artifacts."
                        ),
                        raw_details=str(error),
                    )
                ],
            )

    def sources_state(self, *, session_id: str) -> dict[str, object]:
        """Return the durable, preparation-ordered source manifest."""

        manifest = self._read_source_manifest(session_id)
        if manifest is None:
            return {
                "session_id": session_id,
                "active_source_id": None,
                "sources": [],
            }
        return {
            "session_id": session_id,
            "active_source_id": manifest["active_source_id"],
            "sources": [
                {
                    "source_id": record["source_id"],
                    "filename": record["filename"],
                    "prepared_at": record["prepared_at"],
                }
                for record in manifest["sources"]
            ],
        }

    def active_source_id(self, *, session_id: str) -> str | None:
        manifest = self._read_source_manifest(session_id)
        if manifest is None:
            return None
        active_source_id = manifest["active_source_id"]
        return active_source_id if isinstance(active_source_id, str) else None

    def source_topology(
        self, *, session_id: str, source_id: str
    ) -> dict[str, object]:
        """Load one ready topology without changing the session's active source."""

        self._require_source_record(session_id=session_id, source_id=source_id)
        keys = source_artifact_keys(session_id, source_id)
        try:
            readiness = self.store.read_json(keys["readiness_metadata"])
            topology = self.store.read_json(keys["topology_view_model"])
        except (ArtifactNotFound, ValueError) as error:
            raise ValueError(
                f"Prepared source artifacts are unavailable: {source_id}"
            ) from error
        if (
            not isinstance(readiness, dict)
            or readiness.get("state") != "ready"
            or readiness.get("source_id") != source_id
            or not isinstance(topology, dict)
            or topology.get("source_id") != source_id
        ):
            raise ValueError(
                f"Prepared source artifacts are unavailable: {source_id}"
            )
        return topology

    def activate_source(
        self, *, session_id: str, source_id: str
    ) -> dict[str, object]:
        """Persist a source selection and refresh legacy active-source artifacts."""

        with self._mutation_coordinator.lock(session_id):
            manifest = self._require_source_manifest(session_id)
            self._require_source_record(
                session_id=session_id,
                source_id=source_id,
                manifest=manifest,
            )
            previous_active_source_id = manifest["active_source_id"]
            manifest["active_source_id"] = source_id
            self._commit_manifest_with_aliases(
                session_id=session_id,
                previous_active_source_id=previous_active_source_id,
                next_manifest=manifest,
                next_active_source_id=source_id,
            )
        return {"session_id": session_id, "active_source_id": source_id}

    def delete_source(
        self, *, session_id: str, source_id: str
    ) -> dict[str, object]:
        """Delete one source, committing membership before physical cleanup."""

        with self._mutation_coordinator.lock(session_id):
            manifest = self._require_source_manifest(session_id)
            record_index = self._source_record_index(
                manifest=manifest,
                source_id=source_id,
            )
            if record_index is None:
                raise ReviewSourceNotFound(
                    f"No prepared source is known for session: {session_id}"
                )

            sources = manifest["sources"]
            remaining = [
                record for index, record in enumerate(sources) if index != record_index
            ]
            active_source_id = manifest["active_source_id"]
            if active_source_id == source_id:
                # Match the existing tab close behavior: the last remaining tab
                # becomes active, which makes deleting the active second of two
                # sources select the first.
                next_active_source_id = (
                    remaining[-1]["source_id"] if remaining else None
                )
            else:
                next_active_source_id = active_source_id

            next_manifest = dict(manifest)
            next_manifest["sources"] = remaining
            next_manifest["active_source_id"] = next_active_source_id
            self._commit_manifest_with_aliases(
                session_id=session_id,
                previous_active_source_id=active_source_id,
                next_manifest=next_manifest,
                next_active_source_id=next_active_source_id,
            )

            cleanup_pending = False
            try:
                self.store.delete_tree(source_artifact_prefix(session_id, source_id))
            except Exception:
                # Membership is already committed. Keep the source absent and
                # let a later cleanup/reconciliation pass retry the orphaned
                # tree rather than resurrecting it in the manifest.
                cleanup_pending = True

        result: dict[str, object] = {
            "deleted_source_id": source_id,
            "active_source_id": next_active_source_id,
        }
        if cleanup_pending:
            result["cleanup_pending"] = True
        return result

    def _commit_manifest_with_aliases(
        self,
        *,
        session_id: str,
        previous_active_source_id: object,
        next_manifest: dict[str, object],
        next_active_source_id: object,
    ) -> None:
        """Commit aliases before metadata, rolling them back on failure.

        Aliases are compatibility projections; the source manifest is the
        authority. Before the manifest commit, all source trees remain intact,
        so an alias or manifest failure can preserve the prior logical state.
        """

        try:
            if isinstance(next_active_source_id, str):
                self._sync_active_source_artifacts(
                    session_id=session_id,
                    source_id=next_active_source_id,
                )
            else:
                self._clear_legacy_source_artifacts(session_id)
            self._write_source_manifest(
                session_id=session_id, manifest=next_manifest
            )
        except Exception as error:
            try:
                if isinstance(previous_active_source_id, str):
                    self._sync_active_source_artifacts(
                        session_id=session_id,
                        source_id=previous_active_source_id,
                    )
                else:
                    self._clear_legacy_source_artifacts(session_id)
            except Exception as rollback_error:
                raise RuntimeError(
                    "source manifest transition failed and legacy alias "
                    "rollback also failed; repair is required"
                ) from rollback_error
            raise error


    def _allocate_source_id(
        self, *, session_id: str, content_source_id: str
    ) -> str:
        manifest = self._read_source_manifest(session_id)
        existing_ids = (
            {
                record["source_id"]
                for record in manifest["sources"]
                if isinstance(record.get("source_id"), str)
            }
            if manifest is not None
            else set()
        )
        if content_source_id not in existing_ids:
            return content_source_id
        while True:
            source_id = f"{content_source_id}-{uuid.uuid4().hex[:12]}"
            if source_id not in existing_ids:
                return source_id

    def _record_ready_source(
        self,
        *,
        session_id: str,
        source_id: str,
        filename: str,
    ) -> None:
        with self._mutation_coordinator.lock(session_id):
            manifest = self._read_source_manifest(session_id) or {
                "schema_version": 1,
                "session_id": session_id,
                "active_source_id": None,
                "sources": [],
            }
            previous_active_source_id = manifest["active_source_id"]
            next_manifest = dict(manifest)
            next_manifest["sources"] = [
                *manifest["sources"],
                {
                    "source_id": source_id,
                    "filename": filename,
                    "prepared_at": datetime.now(timezone.utc).isoformat(),
                },
            ]
            next_manifest["active_source_id"] = source_id
            self._commit_manifest_with_aliases(
                session_id=session_id,
                previous_active_source_id=previous_active_source_id,
                next_manifest=next_manifest,
                next_active_source_id=source_id,
            )

    def _sync_active_source_artifacts(
        self, *, session_id: str, source_id: str
    ) -> None:
        source_keys = source_artifact_keys(session_id, source_id)
        for kind, legacy_key in session_artifact_keys(session_id).items():
            self.store.copy(source_keys[kind], legacy_key)

    def _clear_legacy_source_artifacts(self, session_id: str) -> None:
        for key in session_artifact_keys(session_id).values():
            self.store.delete(key)

    def _read_source_manifest(
        self, session_id: str
    ) -> dict[str, object] | None:
        try:
            raw = self.store.read_json(session_sources_manifest_key(session_id))
        except ArtifactNotFound:
            return None
        if not isinstance(raw, dict):
            raise ValueError(f"Invalid source manifest for session: {session_id}")
        sources = raw.get("sources")
        active_source_id = raw.get("active_source_id")
        if (
            raw.get("session_id") != session_id
            or not isinstance(sources, list)
            or (
                active_source_id is not None
                and not isinstance(active_source_id, str)
            )
        ):
            raise ValueError(f"Invalid source manifest for session: {session_id}")

        normalized_sources: list[dict[str, str]] = []
        source_ids: set[str] = set()
        for record in sources:
            if not isinstance(record, dict):
                raise ValueError(
                    f"Invalid source manifest for session: {session_id}"
                )
            source_id = record.get("source_id")
            filename = record.get("filename")
            prepared_at = record.get("prepared_at")
            if (
                not isinstance(source_id, str)
                or not source_id
                or source_id in source_ids
                or not isinstance(filename, str)
                or not isinstance(prepared_at, str)
            ):
                raise ValueError(
                    f"Invalid source manifest for session: {session_id}"
                )
            source_ids.add(source_id)
            normalized_sources.append(
                {
                    "source_id": source_id,
                    "filename": filename,
                    "prepared_at": prepared_at,
                }
            )
        if active_source_id is not None and active_source_id not in source_ids:
            raise ValueError(f"Invalid source manifest for session: {session_id}")
        return {
            "schema_version": raw.get("schema_version"),
            "session_id": session_id,
            "active_source_id": active_source_id,
            "sources": normalized_sources,
        }

    def _require_source_manifest(self, session_id: str) -> dict[str, object]:
        manifest = self._read_source_manifest(session_id)
        if manifest is None:
            raise ValueError(f"No ready topology is known for session: {session_id}")
        return manifest

    def _write_source_manifest(
        self, *, session_id: str, manifest: dict[str, object]
    ) -> None:
        self.store.write_json(session_sources_manifest_key(session_id), manifest)

    def _require_source_record(
        self,
        *,
        session_id: str,
        source_id: str,
        manifest: dict[str, object] | None = None,
    ) -> dict[str, str]:
        resolved_manifest = manifest or self._require_source_manifest(session_id)
        index = self._source_record_index(
            manifest=resolved_manifest,
            source_id=source_id,
        )
        if index is None:
            raise ReviewSourceNotFound(
                f"No prepared source is known for session: {session_id}"
            )
        return resolved_manifest["sources"][index]

    @staticmethod
    def _source_record_index(
        *, manifest: dict[str, object], source_id: str
    ) -> int | None:
        sources = manifest["sources"]
        for index, record in enumerate(sources):
            if record["source_id"] == source_id:
                return index
        return None

    def _failed_result(
        self,
        *,
        session_id: str,
        attempt: int,
        diagnostics: list[dict[str, object]],
        source_id: str | None = None,
    ) -> dict[str, object]:
        readiness = {
            "state": "failed",
            "session_id": session_id,
            "source_id": source_id,
            "diagnostics": diagnostics,
        }
        active_source_id = self.active_source_id(session_id=session_id)
        if active_source_id is None:
            self.store.write_json(f"{session_id}/readiness.json", readiness)
        else:
            # A failed new upload must not turn a previously prepared source
            # into an apparently failed active review.
            self._sync_active_source_artifacts(
                session_id=session_id,
                source_id=active_source_id,
            )
        readiness_path = session_artifact_paths(self.store, session_id)[
            "readiness_metadata"
        ]
        return {
            "session_id": session_id,
            "source_id": source_id,
            "job": {
                "job_id": f"{session_id}:prepare:{attempt}",
                "kind": "session_preparation",
                "status": "failed",
                "stage": "failed",
                "stage_history": [
                    stage("queued", "queued"),
                    stage("failed", "failed"),
                ],
                "attempt": attempt,
            },
            "readiness": readiness,
            "topology_view": None,
            "artifacts": {"readiness_metadata": str(readiness_path)},
            "diagnostics": diagnostics,
        }


def validate_upload_input(
    dexpi_xml_path: Path, *, limits: PreparationLimits | None = None
) -> list[dict[str, object]]:
    limits = limits or PreparationLimits()
    if not dexpi_xml_path.exists():
        return [
            diagnostic(
                code="upload.missing_file",
                message=f"Uploaded process document does not exist: {dexpi_xml_path}",
            )
        ]
    if dexpi_xml_path.suffix.lower() != ".xml":
        return [
            diagnostic(
                code="upload.non_xml",
                message="Uploaded process document must be a supported DEXPI XML file.",
            )
        ]

    upload_bytes = dexpi_xml_path.stat().st_size
    if upload_bytes > limits.max_upload_bytes:
        return [
            diagnostic(
                code="limit.upload_bytes_exceeded",
                message=(
                    f"Uploaded source is {upload_bytes} bytes, exceeding the "
                    f"{limits.max_upload_bytes}-byte upload limit."
                ),
            )
        ]

    try:
        tree = ET.parse(dexpi_xml_path)
    except ET.ParseError as error:
        return [
            diagnostic(
                code="upload.xml_parse_failed",
                message="Uploaded XML could not be parsed.",
                raw_details=str(error),
            )
        ]

    root = tree.getroot()
    plant_information = root.find("PlantInformation")
    application = (
        plant_information.attrib.get("Application", "")
        if plant_information is not None
        else ""
    )
    if root.tag != "PlantModel" or application.lower() != "dexpi":
        return [
            diagnostic(
                code="upload.non_dexpi_xml",
                message="Uploaded XML is not a DEXPI PlantModel document.",
            )
        ]

    element_count = sum(1 for _ in root.iter())
    if element_count > limits.max_xml_elements:
        return [
            diagnostic(
                code="limit.xml_elements_exceeded",
                message=(
                    f"Uploaded source has {element_count} XML elements, exceeding the "
                    f"{limits.max_xml_elements}-element complexity limit."
                ),
            )
        ]

    element_depth = _xml_depth(root)
    if element_depth > limits.max_xml_depth:
        return [
            diagnostic(
                code="limit.xml_depth_exceeded",
                message=(
                    f"Uploaded source nests {element_depth} XML levels, exceeding the "
                    f"{limits.max_xml_depth}-level complexity limit."
                ),
            )
        ]

    return []


def _xml_depth(element: ET.Element) -> int:
    return 1 + max((_xml_depth(child) for child in element), default=0)


def check_graph_size_limits(
    *, graph: dict[str, object], limits: PreparationLimits
) -> list[dict[str, object]]:
    node_count = int(graph.get("node_count", 0))
    if node_count > limits.max_graph_nodes:
        return [
            diagnostic(
                code="limit.graph_nodes_exceeded",
                message=(
                    f"Extracted graph has {node_count} nodes, exceeding the "
                    f"{limits.max_graph_nodes}-node graph limit."
                ),
            )
        ]
    edge_count = int(graph.get("edge_count", 0))
    if edge_count > limits.max_graph_edges:
        return [
            diagnostic(
                code="limit.graph_edges_exceeded",
                message=(
                    f"Extracted graph has {edge_count} edges, exceeding the "
                    f"{limits.max_graph_edges}-edge graph limit."
                ),
            )
        ]
    return []


def check_preparation_time_limit(
    *, elapsed_seconds: float, limits: PreparationLimits
) -> list[dict[str, object]]:
    if elapsed_seconds > limits.max_preparation_seconds:
        return [
            diagnostic(
                code="limit.preparation_time_exceeded",
                message=(
                    f"Preparation took {elapsed_seconds:.3f}s, exceeding the "
                    f"{limits.max_preparation_seconds}s processing-time limit."
                ),
            )
        ]
    return []


def check_artifact_size_limits(
    *,
    store: ArtifactStore,
    session_id: str,
    limits: PreparationLimits,
    source_id: str | None = None,
) -> list[dict[str, object]]:
    for kind, key in sorted(session_artifact_keys(session_id, source_id).items()):
        if not store.exists(key):
            continue
        artifact_bytes = store.size(key)
        if artifact_bytes > limits.max_artifact_bytes:
            return [
                diagnostic(
                    code="limit.artifact_bytes_exceeded",
                    message=(
                        f"Prepared artifact '{kind}' is {artifact_bytes} bytes, "
                        f"exceeding the {limits.max_artifact_bytes}-byte artifact limit."
                    ),
                )
            ]
    return []


def build_topology_view_model(
    *,
    graph_facts: dict[str, object],
    session_id: str,
    source_id: str | None = None,
    dexpi_xml_path: Path | None = None,
) -> dict[str, object]:
    # Document-level provenance; kept distinct from per-edge graph endpoint ids
    # (which also use the name "source_id") below.
    document_source_id = source_id
    fact_nodes = graph_facts["facts"]["nodes"]
    fact_edges = graph_facts["facts"]["edges"]

    node_ids_by_raw_id = build_stable_node_id_map(fact_nodes)
    display_names = derive_display_names(fact_nodes, fact_edges)
    nodes = []
    evidence_map: dict[str, dict[str, object]] = {}
    for node in sorted(
        fact_nodes, key=lambda item: node_ids_by_raw_id[item["node_id"]]
    ):
        stable_node_id = node_ids_by_raw_id[node["node_id"]]
        naming = display_names.get(node["node_id"], {})
        nodes.append(
            {
                "id": stable_node_id,
                # `label` stays the raw DEXPI class for downstream Datalog/semantics.
                "label": node["attributes"].get("label", stable_node_id),
                "tag_name": node["attributes"].get("tagName"),
                # Engineer-facing identifiers derived from the DEXPI hierarchy.
                "display_name": naming.get("display_name") or stable_node_id,
                "class_name": naming.get("class_name", ""),
                "category": naming.get("category", "other"),
                "description": naming.get("description", ""),
                "proteus_id": node["attributes"].get("proteusId"),
                "canonical_fact_id": stable_node_id,
                "source_graph_node_id": node["node_id"],
            }
        )
        evidence_map[stable_node_id] = {
            "kind": "node",
            "topology_id": stable_node_id,
            "source_id": document_source_id,
            "canonical_fact": {
                "fact_type": "node",
                "node_id": node["node_id"],
            },
        }

    # A review witness must be highlightable. Include every generic review edge
    # plus the narrower canonical process-piping associations used by reachability.
    review_topology_attr_names = TOPOLOGY_ATTR_NAMES | PROCESS_PIPING_ATTR_NAMES
    topology_edges = []
    for edge in sorted(
        fact_edges,
        key=lambda item: (
            item["source_id"],
            item["target_id"],
            str(item["edge_key"]),
            str(item["attributes"].get("attr_name", "")),
        ),
    ):
        attr_name = edge["attributes"].get("attr_name")
        if attr_name not in review_topology_attr_names:
            continue
        edge_key = str(edge["edge_key"])
        source_id = node_ids_by_raw_id[edge["source_id"]]
        target_id = node_ids_by_raw_id[edge["target_id"]]
        edge_id = stable_hash_id(
            "edge",
            {
                "source_id": source_id,
                "target_id": target_id,
                "edge_key": edge_key,
                "relationship": attr_name,
                "edge_family": edge["attributes"].get("label"),
            },
        )
        topology_edges.append(
            {
                "id": edge_id,
                "source_id": source_id,
                "target_id": target_id,
                "relationship": attr_name,
                "edge_family": edge["attributes"].get("label"),
                "canonical_fact_id": edge_id,
                "source_graph_edge": {
                    "source_id": edge["source_id"],
                    "target_id": edge["target_id"],
                    "edge_key": edge_key,
                },
            }
        )
        evidence_map[edge_id] = {
            "kind": "edge",
            "topology_id": edge_id,
            "source_id": document_source_id,
            "canonical_fact": {
                "fact_type": "edge",
                "source_id": edge["source_id"],
                "target_id": edge["target_id"],
                "edge_key": edge_key,
            },
        }

    raw_schematic_scene = None
    if dexpi_xml_path is not None:
        proteus_id_to_topology_id = {
            node["proteus_id"]: node["id"] for node in nodes if node.get("proteus_id")
        }
        raw_schematic_scene = build_schematic_scene_report(
            dexpi_xml_path=dexpi_xml_path,
            proteus_id_to_topology_id=proteus_id_to_topology_id,
            namespace=document_source_id or session_id,
        )

    # Geometry sanity gate (bead pydexpi-datalog-1-2ki.5): the gate outcome,
    # not just geometry presence, decides whether the scene is disclosed as
    # drawn. Files failing the gate degrade to the auto-layout schematic view
    # (frontend-computed, per ADR 0005's tolerated client-side exception) --
    # source positions are never mixed with invented ones, so a gate failure
    # drops the scene entirely rather than presenting it partially "as drawn".
    geometry_report = evaluate_geometry_gate(raw_schematic_scene)
    drawable = raw_schematic_scene is not None and has_drawable_geometry(raw_schematic_scene)
    if drawable and geometry_report["passed"]:
        schematic_scene = raw_schematic_scene
        schematic_scene_kind = "as-drawn"
    elif raw_schematic_scene is not None:
        schematic_scene = None
        schematic_scene_kind = "auto-layout"
    else:
        schematic_scene = None
        schematic_scene_kind = "none"

    return {
        "schema_version": "topology-view.v1",
        "session_id": session_id,
        "source_id": document_source_id,
        "source_path": graph_facts["source_path"],
        "nodes": nodes,
        "edges": topology_edges,
        "evidence_map": evidence_map,
        # P&ID-like compression: equipment units + collapsed lines, for the graph panel.
        "pid_view": build_pid_view(nodes, fact_edges),
        # Drawing-faithful tier-1 scene (ADR 0004/0005); None when the source
        # carries no geometry, or when the geometry sanity gate fails
        # (bead pydexpi-datalog-1-2ki.5) -- source positions are never
        # disclosed as drawn once the gate rejects them.
        "schematic_scene": schematic_scene,
        # "as-drawn" | "auto-layout" | "none" -- the gate's disclosure of
        # which schematic tier the frontend must present. Kept backend-owned
        # even though auto-layout position computation itself may run
        # client-side (ADR 0005).
        "schematic_scene_kind": schematic_scene_kind,
        "geometry_report": geometry_report,
        "evidence_highlight": {
            "source_scope_ids": [],
            "matched_object_ids": [],
            "paths": [],
        },
    }


def build_stable_node_id_map(fact_nodes: list[dict[str, object]]) -> dict[str, str]:
    ids_by_raw_id: dict[str, str] = {}
    signature_counts: dict[str, int] = {}
    for node in sorted(
        fact_nodes,
        key=lambda item: json.dumps(item["attributes"], sort_keys=True),
    ):
        stable_base = stable_hash_id("node", node["attributes"])
        signature_counts[stable_base] = signature_counts.get(stable_base, 0) + 1
        suffix = signature_counts[stable_base]
        stable_id = stable_base if suffix == 1 else f"{stable_base}-{suffix}"
        ids_by_raw_id[node["node_id"]] = stable_id
    return ids_by_raw_id


def build_evidence_highlight_payload(
    *,
    topology_view: dict[str, object],
    source_scope_ids: list[str],
    matched_object_ids: list[str],
    paths: list[dict[str, object]],
) -> dict[str, object]:
    known_ids = set(topology_view["evidence_map"])
    highlight_ids = set(source_scope_ids) | set(matched_object_ids)
    for path in paths:
        highlight_ids.update(path.get("node_ids", []))
        highlight_ids.update(path.get("edge_ids", []))

    unknown_ids = sorted(highlight_ids - known_ids)
    if unknown_ids:
        raise ValueError(f"unknown topology id in evidence highlight: {unknown_ids[0]}")

    return {
        "source_scope_ids": list(source_scope_ids),
        "matched_object_ids": list(matched_object_ids),
        "paths": [
            {
                "id": path["id"],
                "node_ids": list(path.get("node_ids", [])),
                "edge_ids": list(path.get("edge_ids", [])),
            }
            for path in paths
        ],
    }


def stable_hash_id(prefix: str, payload: object) -> str:
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def diagnostic(
    *, code: str, message: str, raw_details: str | None = None
) -> dict[str, object]:
    item: dict[str, object] = {
        "severity": "error",
        "code": code,
        "message": message,
    }
    if raw_details is not None:
        item["raw_details"] = raw_details
    return item


def stage(status: str, text: str) -> dict[str, str]:
    return {"status": status, "text": text}


def session_sources_manifest_key(session_id: str) -> str:
    """The durable source-record manifest for one review session."""

    return f"{session_id}/sources.json"


def source_artifact_prefix(session_id: str, source_id: str) -> str:
    """The contained artifact tree for one independently prepared source."""

    return f"{session_id}/sources/{source_id}"


def source_artifact_keys(session_id: str, source_id: str) -> dict[str, str]:
    """The source-scoped counterparts to the legacy active-session artifacts."""

    prefix = source_artifact_prefix(session_id, source_id)
    return {
        "graph_facts_json": f"{prefix}/graph_facts.json",
        "graph_facts_datalog": f"{prefix}/graph_facts.dl",
        "derived_graph_semantics_datalog": (
            f"{prefix}/derived_graph_semantics.dl"
        ),
        "readiness_metadata": f"{prefix}/readiness.json",
        "topology_view_model": f"{prefix}/topology_view.json",
    }


def session_artifact_keys(
    session_id: str, source_id: str | None = None
) -> dict[str, str]:
    """Prepared artifact keys for a source, or legacy active-source aliases.

    Callers that do not know about source records keep the established flat
    layout and therefore continue to resolve the persisted active source.
    New source-aware callers pass ``source_id`` and never share artifacts with
    another document in the same review session.
    """

    if source_id is not None:
        return source_artifact_keys(session_id, source_id)
    return {
        "graph_facts_json": f"{session_id}/{session_id}/graph_facts.json",
        "graph_facts_datalog": f"{session_id}/graph_facts.dl",
        "derived_graph_semantics_datalog": (
            f"{session_id}/derived_graph_semantics.dl"
        ),
        "readiness_metadata": f"{session_id}/readiness.json",
        "topology_view_model": f"{session_id}/topology_view.json",
    }


def session_artifact_paths(
    store: ArtifactStore, session_id: str, source_id: str | None = None
) -> dict[str, str]:
    """Where each source's artifacts can be fetched in every deployment."""

    return {
        role: store.download_url(key)
        for role, key in session_artifact_keys(session_id, source_id).items()
    }
