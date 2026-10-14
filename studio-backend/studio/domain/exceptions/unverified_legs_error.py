"""Raised when app-side conformance legs report skipped and no waiver was given."""

from __future__ import annotations

from studio.domain.exceptions.app_error import AppError
from studio.domain.model.conformance_report import ConformanceReport

__all__ = ["APP_REPO_ROW", "APP_SIDE_LEGS", "UnverifiedLegsError"]

# The repository every other app-side leg is read through. It is judged on its
# own row so an unreadable repo says so once, instead of surfacing as four
# downstream legs each naming a different artifact to stand up.
APP_REPO_ROW = "install/delivery::app-repo-readable"

# The conformance legs read off the app's own delivery artifacts (the
# team-owned side). Each maps to what makes it readable, so a refusal tells
# the caller exactly which artifact to stand up first.
APP_SIDE_LEGS: dict[str, str] = {
    APP_REPO_ROW: (
        "readable once the repository the Application's repoURL names exists "
        "under the org and the studio's token is granted it; onboard with an "
        "explicit repo when the app's repository is named differently from "
        "the app"
    ),
    "install/delivery::ci-caller": (
        "readable once the app repo's .github/workflows/build.yml exists on "
        "the repo host, calling the shared ci reusable workflow, the "
        "studio's token can read the repo, and its read answers"
    ),
    "install/delivery::deploy-branch": (
        "readable once the deploy-<install> branch exists in the app repo, "
        "carrying one folder per declared environment with values.yaml plus Chart.yaml"
    ),
    "install/promotion::image-updater-promotes": (
        "readable once that branch's entry environment values carry the image tag "
        "path(s) the Application's Image Updater bindings write"
    ),
    "install/promotion::image-updater-released-set": (
        "readable once the app repo's default branch carries a parseable "
        "devops/docker-compose.yml naming the images CI publishes"
    ),
    "install/onboarding::docs-image": (
        "readable once the app repo itself is readable and its docs/Dockerfile "
        "read answers; the row then requires docs/Dockerfile on the default "
        "branch (the source of the <app>-docs image) - no docs, no onboard, and "
        "a repo whose default-branch listing answers without it FAILS rather "
        "than skips, which no allow_bootstrap waives"
    ),
}


class UnverifiedLegsError(AppError):
    """The change was rolled back: the app's app-side legs are unverified.

    A skipped leg means the app's own delivery artifacts could not be read at
    conformance time, so admitting the change would ship an app whose team
    side is entirely unverified and park the merged Application in
    ComparisonError until the app repo catches up. Strict by default, forcing
    the artifacts-first ordering; the explicit allow_bootstrap waiver admits
    the deliberate walking-skeleton bootstrap.
    """

    def __init__(self, report: ConformanceReport, skipped: tuple[str, ...]) -> None:
        # A row's own detail names the artifact it actually read (the repo URL
        # that would not answer); the static remedy is the fallback for rows
        # that carry none.
        details = {
            result.node_id: result.detail for result in report.results if result.detail
        }
        legs = "; ".join(
            f"{node_id} ({details.get(node_id) or self._remedy(node_id)})"
            for node_id in skipped
        )
        super().__init__(
            "app-side conformance legs are unverified; change rolled back. "
            f"Skipped: {legs}. Stand those artifacts up first, or pass "
            "allow_bootstrap=true to admit the walking-skeleton bootstrap "
            "deliberately."
        )
        self.report = report
        self.skipped = skipped

    @staticmethod
    def _remedy(node_id: str) -> str:
        for prefix, remedy in APP_SIDE_LEGS.items():
            if node_id.startswith(prefix):
                return remedy
        return "unreadable app-side leg"
