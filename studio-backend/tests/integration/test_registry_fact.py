"""The install's registry fact drives every render (INT-REGISTRY-001).

The fact is read off the deploy branch's values.yaml `registry` block
(ADR-044, the platform's #164); a branch declaring none falls back to GHCR
under the app-repo org, the shape its pre-2.2.0 chart carries itself. The
refusal half of the claim (a declared non-GHCR host is never silently asked
of the GHCR packages API) lives in OnboardApp._ensure_deploy_branch, which
gates on the same `declared`/`host` facts these tests pin.
"""

from __future__ import annotations

from pathlib import Path

from pytest_intent import intent

from studio.adapters.outbound.platform_fs.fs_platform_repository import FsPlatformRepository
from studio.domain.services.app_repo_scaffold import render_app_repo_scaffold
from studio.domain.services.deploy_branch import render_deploy_branch
from studio.domain.services.image_promotion import (
    image_updater_annotation_lines,
    image_updater_problems,
)

_ECR = "123456789.dkr.ecr.eu-west-1.amazonaws.com/acme"


@intent("INT-REGISTRY-001")
def test_fs_repository_reads_the_registry_block(platform_root: Path) -> None:
    values = platform_root / "values.yaml"
    values.write_text(
        values.read_text(encoding="utf-8")
        + "registry:\n  host: ghcr.io\n  owner: test-org\n  pullSecret: ghcr-pull\n",
        encoding="utf-8",
    )
    registry = FsPlatformRepository(platform_root).registry()
    assert registry.declared
    assert registry.prefix == "ghcr.io/test-org"
    assert registry.pull_secret == "ghcr-pull"


@intent("INT-REGISTRY-001")
def test_a_declared_empty_pull_secret_is_kept_not_defaulted(platform_root: Path) -> None:
    """Declared-and-empty is the node-identity shape, not a missing value."""
    values = platform_root / "values.yaml"
    values.write_text(
        values.read_text(encoding="utf-8")
        + f"registry:\n  host: {_ECR.split('/', 1)[0]}\n  owner: acme\n  pullSecret: \"\"\n",
        encoding="utf-8",
    )
    registry = FsPlatformRepository(platform_root).registry()
    assert registry.declared
    assert registry.pull_secret_or_ghcr() == ""


@intent("INT-REGISTRY-001")
def test_an_undeclared_registry_falls_back_to_ghcr(platform_root: Path) -> None:
    """The fixture's values.yaml declares no block: the pre-2.2.0 branch shape."""
    registry = FsPlatformRepository(platform_root).registry()
    assert not registry.declared
    assert registry.prefix_or_ghcr("Test-Org") == "ghcr.io/test-org"
    assert registry.pull_secret_or_ghcr() == "ghcr-pull"
    # The refusal gate in OnboardApp never fires for an undeclared branch.
    assert not (registry.declared and registry.host != "ghcr.io")


@intent("INT-REGISTRY-001")
def test_renders_follow_a_declared_registry() -> None:
    """Deploy branch, Image Updater annotations, and scaffold all carry the
    declared prefix, and nothing renders ghcr.io for an install elsewhere."""
    deploy = dict(
        render_deploy_branch(
            app="gamma-app",
            registry=_ECR,
            components=("app", "docs"),
            chart_version="1.0.0",
            image_tags={"gamma-app-app": "1.0.0", "gamma-app-docs": "1.0.0"},
            zone="lab.example.dev",
            environments=("prod",),
        )
    )
    rendered = "\n".join(deploy.values())
    assert f"repository: {_ECR}/gamma-app-app" in rendered
    assert f"repository: oci://{_ECR}/charts" in rendered
    assert "ghcr.io" not in rendered

    annotations = image_updater_annotation_lines(
        app="gamma-app", registry=_ECR, components=("app", "docs")
    )
    assert f"app={_ECR}/gamma-app-app" in annotations
    assert "ghcr.io" not in annotations

    # The coherence check holds the annotations to the same declared registry.
    parsed = {
        line.split(": ", 1)[0].strip(): line.split(": ", 1)[1]
        for line in annotations.splitlines()
    }
    assert not image_updater_problems(
        app="gamma-app", repo_owner="Test-Org", annotations=parsed, registry=_ECR
    )

    files = render_app_repo_scaffold(
        app="gamma-app",
        display_name="Gamma App",
        description="The gamma application.",
        registry=_ECR,
        pull_secret="",
    )
    chart_values = files["k8s/values.yaml"]
    assert f"repository: {_ECR}/gamma-app-app" in chart_values
    assert "imagePullSecrets: []" in chart_values
    assert "ghcr.io" not in chart_values
