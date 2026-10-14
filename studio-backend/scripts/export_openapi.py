"""Export the OpenAPI contract with the full capability surface.

The PR routes exist only in the PR-capable composition, so the export wires
stub outbound adapters that satisfy every port; the emitted contract is the
superset the SPA generates its types from.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("STUDIO_AUTH_DISABLED", "true")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio.adapters.inbound.http.app import create_app  # noqa: E402
from studio.adapters.outbound.http_probe.noop_http_probe import NoopHttpProbe  # noqa: E402
from studio.container import Container  # noqa: E402
from studio.domain.model.conformance_report import ConformanceReport  # noqa: E402
from studio.domain.model.pr_info import PrInfo  # noqa: E402


class _StubConformance:
    def run(self) -> ConformanceReport:
        return ConformanceReport(exit_code=0, results=(), output="")


class _StubGitPr:
    def prepare_branch(self, name: str) -> None:
        return None

    def commit_to_deploy(self, *, paths: tuple[str, ...], commit_message: str) -> None:
        return None

    def finalize(
        self, *, branch: str, commit_message: str, pr_title: str, pr_body: str
    ) -> PrInfo | None:
        return None

    def abort(self, branch: str) -> None:
        return None

    def delete_remote_branch(self, branch: str) -> bool:
        return False

    def open_prs(self) -> tuple[PrInfo, ...]:
        return ()

    def prs_for_branch(self, branch: str) -> tuple[PrInfo, ...]:
        return ()

    def get_pr(self, number: int) -> PrInfo:
        return PrInfo(
            number=number,
            title="stub",
            url="https://github.example/stub/pulls/0",
            branch="onboard/stub",
            state="open",
            merged=False,
        )

    def refresh(self) -> None:
        return None


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "teams").mkdir(parents=True)
        (root / "foundry.yaml").write_text("parts: []\noutput: []\n", encoding="utf-8")
        (root / "values.yaml").write_text("zone: example.dev\n", encoding="utf-8")
        (root / "intent.yaml").write_text("", encoding="utf-8")
        container = Container(
            platform_root=root,
            conformance=_StubConformance(),
            git_pr=_StubGitPr(),
            http_probe=NoopHttpProbe(),
        )
        app = create_app(container)
    out = Path(__file__).resolve().parents[1] / "openapi.json"
    out.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
