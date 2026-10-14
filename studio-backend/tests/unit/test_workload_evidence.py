"""Workload readiness requires regular containers and the pod readiness gate."""

from __future__ import annotations

import pytest

from studio.domain.model.link_status import LinkStatus
from studio.domain.services.cluster_evidence import workload_evidence


@pytest.mark.parametrize(
    ("regular_ready", "terminated", "pod_ready", "expected"),
    [
        (True, False, "True", LinkStatus.OK),
        (False, True, "True", LinkStatus.PENDING),
        (True, False, "False", LinkStatus.PENDING),
        (True, False, None, LinkStatus.PENDING),
    ],
)
def test_successful_init_does_not_supply_regular_or_pod_readiness(
    regular_ready: bool,
    terminated: bool,
    pod_ready: str | None,
    expected: LinkStatus,
) -> None:
    status = {
        "phase": "Running",
        "initContainerStatuses": [
            {
                "name": "setup",
                "ready": False,
                "state": {"terminated": {"exitCode": 0}},
            }
        ],
        "containerStatuses": [
            {
                "name": "app",
                "ready": regular_ready,
                "state": {"terminated": {"exitCode": 0}} if terminated else {"running": {}},
            }
        ],
    }
    if pod_ready is not None:
        status["conditions"] = [{"type": "Ready", "status": pod_ready}]
    pod = {"metadata": {"name": "app-pod"}, "status": status}
    if pod_ready == "False":
        pod["spec"] = {"readinessGates": [{"conditionType": "example.com/ready"}]}
        status["conditions"].append({"type": "example.com/ready", "status": "False"})
    result = workload_evidence((pod,))
    assert result.status is expected
    assert f"Pod Ready {pod_ready or 'Unknown'}" in result.detail
