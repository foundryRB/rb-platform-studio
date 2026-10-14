"""INT-GRANT-006: the event-bus grant is rendered from the studio's own canonical
template, and the properties that keep an app's key private and its voice its own
hold for any app name and any domain set."""

from __future__ import annotations

import pytest
import yaml
from pytest_intent import intent

from studio.domain.services.events_grant import (
    APP_PLACEHOLDER,
    EVENTS_NAMESPACE,
    SIGNER_SECRET,
    events_grant_is_self_consistent,
    normalise_domains,
    render_events_grant,
)


def _docs(block: str) -> list[dict]:
    return [doc for doc in yaml.safe_load_all(block) if isinstance(doc, dict)]


def _job(block: str, name: str) -> dict:
    return next(
        doc
        for doc in _docs(block)
        if doc["kind"] == "Job" and doc["metadata"]["name"] == name
    )


def _scripts(job: dict) -> str:
    spec = job["spec"]["template"]["spec"]
    parts: list[str] = []
    for container in list(spec.get("initContainers") or []) + list(spec.get("containers") or []):
        parts.extend(str(piece) for piece in container.get("command") or [])
    return "\n".join(parts)


@intent("INT-GRANT-006")
@pytest.mark.parametrize("app", ["platform-studio", "scrapyard", "alpha-app"])
def test_rendered_grant_is_self_consistent_for_any_app(app: str) -> None:
    block = render_events_grant(app, ["platform"])
    assert APP_PLACEHOLDER not in block
    assert events_grant_is_self_consistent(block_text=block, app=app, domains=("platform",))

    # Both halves of the grant are present and land in the right namespace.
    gen = _job(block, f"gen-nats-{app}")
    sign = _job(block, f"nats-sign-{app}")
    assert gen["metadata"]["namespace"] == app
    assert sign["metadata"]["namespace"] == EVENTS_NAMESPACE


@intent("INT-GRANT-006")
@pytest.mark.parametrize("app", ["platform-studio", "scrapyard"])
def test_the_seed_never_leaves_the_apps_namespace(app: str) -> None:
    """The private half is never annotated for reflection, and never mounted out."""
    block = render_events_grant(app, ["platform"])
    scripts = _scripts(_job(block, f"gen-nats-{app}"))

    # The seed secret is created, and never told it may travel.
    assert f"kubectl create secret generic nats-{app} -n {app}" in scripts
    assert f"kubectl annotate secret nats-{app} -n {app}" not in scripts
    # Only the public half is annotated, and only into messaging.
    assert f"kubectl annotate secret nats-{app}-pub -n {app}" in scripts
    assert f"reflection-auto-namespaces={EVENTS_NAMESPACE}" in scripts
    # Generate-if-absent: the create is guarded, so a re-run never rotates.
    guard = scripts.index(f"if kubectl get secret nats-{app} -n {app}")
    create = scripts.index(f"kubectl create secret generic nats-{app} -n {app}")
    assert guard < create
    # The signing material is nowhere near the app's namespace.
    assert SIGNER_SECRET not in yaml.safe_dump(_job(block, f"gen-nats-{app}"))


@intent("INT-GRANT-006")
def test_only_the_signing_job_mounts_the_signing_key() -> None:
    block = render_events_grant("platform-studio", ["platform"])
    assert block.count(f"secretName: {SIGNER_SECRET}") == 1
    sign = _job(block, "nats-sign-platform-studio")
    mounted = {
        volume.get("secret", {}).get("secretName")
        for volume in sign["spec"]["template"]["spec"]["volumes"]
    }
    assert SIGNER_SECRET in mounted


@intent("INT-GRANT-006")
@pytest.mark.parametrize(
    "domains,expected",
    [
        (["platform"], ("platform",)),
        (["Platform", " delivery "], ("platform", "delivery")),
        (["platform", "platform"], ("platform",)),
    ],
)
def test_domains_are_normalised(domains: list[str], expected: tuple[str, ...]) -> None:
    assert normalise_domains(domains) == expected


@intent("INT-GRANT-006")
@pytest.mark.parametrize("domains", [[], ["Not A Domain"], ["-leading"], ["with.dot"]])
def test_a_bad_domain_set_is_refused(domains: list[str]) -> None:
    """Refused before any branch is prepared, so no empty PR is ever opened."""
    with pytest.raises(ValueError):
        render_events_grant("platform-studio", domains)


@intent("INT-GRANT-006")
def test_publishing_is_scoped_and_reading_is_open() -> None:
    """The signed permissions are the contract: owned domains out, everything in."""
    block = render_events_grant("platform-studio", ["platform", "delivery"])
    scripts = _scripts(_job(block, "nats-sign-platform-studio"))

    assert "--allow-pub 'com.foundry.platform.>'" in scripts
    assert "--allow-pub 'com.foundry.delivery.>'" in scripts
    # Reading is open across the whole space (REF-Events section 8).
    assert "--allow-sub 'com.foundry.>'" in scripts
    # A domain the app does not own is not publishable.
    assert "--allow-pub 'com.foundry.routine.>'" not in scripts
    # The JetStream grant is scoped to the one shared stream, never the whole
    # control plane.
    assert "--allow-pub '$JS.API.>'" not in scripts
    assert "--allow-pub '$JS.API.STREAM.INFO.FOUNDRY_EVENTS'" in scripts
    # The user is signed for a public key, so no seed is ever in the store.
    assert "--public-key" in scripts
    assert "nk -gen" not in scripts


@intent("INT-GRANT-006")
def test_the_jwt_returns_by_reflection_not_by_cross_namespace_write() -> None:
    block = render_events_grant("scrapyard", ["platform"])
    sign = _job(block, "nats-sign-scrapyard")
    scripts = _scripts(sign)

    # Written in messaging, annotated to travel back to the app's namespace.
    assert f"kubectl create secret generic nats-jwt-scrapyard -n {EVENTS_NAMESPACE}" in scripts
    assert "reflection-auto-namespaces=scrapyard" in scripts
    # The signing Job's RBAC never reaches into the app's namespace.
    roles = [doc for doc in _docs(block) if doc["kind"] == "Role"]
    signer_role = next(r for r in roles if r["metadata"]["name"] == "nats-sign-scrapyard")
    assert signer_role["metadata"]["namespace"] == EVENTS_NAMESPACE
    named = {name for rule in signer_role["rules"] for name in rule.get("resourceNames", [])}
    assert named == {"nats-scrapyard-pub", "nats-jwt-scrapyard"}
