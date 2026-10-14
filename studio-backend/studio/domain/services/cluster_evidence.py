"""Verdicts over primary Application and workload observations."""

from __future__ import annotations

from studio.domain.model.link_status import LinkStatus
from studio.domain.model.status_link import StatusLink

__all__ = ["sync_evidence", "workload_evidence"]


def sync_evidence(application: dict | None, requested: str | None) -> StatusLink:
    if application is None:
        return StatusLink(LinkStatus.SKIPPED, "Application read unavailable; sync unknown")
    status = application.get("status") or {}
    sync = status.get("sync") or {}
    operation = status.get("operationState") or {}
    state = str(sync.get("status") or "Unknown")
    applied = str(sync.get("revision") or "<unknown>")
    phase = str(operation.get("phase") or "<unknown>")
    detail = (
        f"sync {state}; applied revision {applied}; requested revision {requested or '<unknown>'}; "
        f"operation {phase}: {operation.get('message') or '<no message>'}"
    )
    if phase in {"Failed", "Error"}:
        return StatusLink(LinkStatus.FAILED, detail)
    if state == "OutOfSync" or phase in {"Running", "Terminating"}:
        return StatusLink(LinkStatus.PENDING, detail)
    if state == "Synced" and requested and applied == requested and phase == "Succeeded":
        return StatusLink(LinkStatus.OK, detail)
    return StatusLink(LinkStatus.SKIPPED, f"{detail}; applied sync unverified")


def workload_evidence(pods: tuple[dict, ...] | None) -> StatusLink:
    if pods is None:
        return StatusLink(LinkStatus.SKIPPED, "Pod read unavailable; workload unknown")
    active = [
        p
        for p in pods
        if not (p.get("metadata") or {}).get("deletionTimestamp")
        and (p.get("status") or {}).get("phase") not in {"Succeeded"}
    ]
    if not active:
        return StatusLink(LinkStatus.SKIPPED, "No active workload pods; workload unknown")
    details: list[str] = []
    failed = False
    pending = False
    observed = False
    for pod in active:
        name = str((pod.get("metadata") or {}).get("name") or "<unknown>")
        status = pod.get("status") or {}
        ready = next(
            (
                condition.get("status")
                for condition in status.get("conditions") or []
                if condition.get("type") == "Ready"
            ),
            "Unknown",
        )
        details.append(f"{name}: Pod Ready {ready}")
        containers = [
            *((container, True) for container in status.get("initContainerStatuses") or []),
            *((container, False) for container in status.get("containerStatuses") or []),
        ]
        pending |= status.get("phase") != "Running" or not containers
        pending |= ready != "True"
        failed |= status.get("phase") == "Failed"
        for container, is_init in containers:
            observed = True
            waiting = (container.get("state") or {}).get("waiting") or {}
            terminated = (container.get("state") or {}).get("terminated") or {}
            last = (container.get("lastState") or {}).get("terminated") or {}
            reason = str(waiting.get("reason") or "none")
            exit_code = last.get("exitCode", terminated.get("exitCode", "none"))
            details.append(
                f"{name}/{container.get('name')}: waiting {reason}; "
                f"last exit {exit_code}; restarts {container.get('restartCount', 0)}"
            )
            failed |= reason in {
                "CrashLoopBackOff",
                "CreateContainerConfigError",
                "ImagePullBackOff",
                "ErrImagePull",
            }
            failed |= bool(terminated) and terminated.get("exitCode", 0) != 0
            # Completed init containers are healthy, even though ready is false.
            complete = is_init and terminated.get("exitCode") == 0
            pending |= not container.get("ready", False) and not complete
    verdict = (
        LinkStatus.FAILED
        if failed
        else LinkStatus.PENDING
        if pending
        else LinkStatus.OK
        if observed
        else LinkStatus.SKIPPED
    )
    return StatusLink(verdict, "; ".join(details) or "Container status unavailable")
