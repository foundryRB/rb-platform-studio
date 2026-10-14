"""The in-cluster credential generator renders well-formed, self-consistent YAML.

The generator Job is the value-creation counterpart of the database and realm
provisioning Jobs: it mints the app-owned ``pg-app-<app>`` / ``keycloak-<app>``
credential in-cluster if absent, so an autonomous delivery needs no app-side
secret script and no local apply-secrets run. These tests prove the rendered
block is valid multi-document YAML (the real risk is the block-scalar script
indentation), names a per-app credential, guards generation behind an existence
check (never a blind rotate), converges the reflector annotations on every run
(so a run that died between create and annotate heals on the next sync), keeps
an in-place Class 3a secret free of reflector annotations, and fails closed on a
regressed render.
"""

from __future__ import annotations

import pytest
import yaml
from pytest_intent import intent

from studio.domain.services.secret_generator import (
    APP_PLACEHOLDER,
    GeneratedSecret,
    keycloak_secret,
    pg_app_secret,
    render_secret_generator,
    secret_generator_is_self_consistent,
)

APPS = ["scrapyard", "sabbito-bazarrito", "alpha-app"]


def _runtime_auth_secret(app: str) -> GeneratedSecret:
    """A Class 3a machine-door credential: pure random, in place (no reflection)."""
    return GeneratedSecret(
        secret_name=f"{app}-auth",
        secret_type=None,
        literals=(("STUDIO_AUTH_USER", app),),
        random_keys=(("STUDIO_AUTH_PASSWORD", "hex", 24),),
        reflect_namespace=None,
    )


@intent("INT-GRANT-003")
@pytest.mark.parametrize("app", APPS)
@pytest.mark.parametrize("make_spec", [pg_app_secret, keycloak_secret, _runtime_auth_secret])
def test_render_is_well_formed_and_self_consistent(app: str, make_spec) -> None:
    spec = make_spec(app)
    block = render_secret_generator(app, spec)

    # No placeholder survives, and the studio's own gate passes on its own output.
    assert APP_PLACEHOLDER not in block
    assert secret_generator_is_self_consistent(block_text=block, app=app, spec=spec)

    # Valid multi-document YAML: ServiceAccount, Role, RoleBinding, Job.
    docs = [d for d in yaml.safe_load_all(block) if d is not None]
    kinds = [d["kind"] for d in docs]
    assert kinds == ["ServiceAccount", "Role", "RoleBinding", "Job"]

    # Everything is named for the app and lives in the app's namespace.
    name = f"gen-{spec.secret_name}"
    assert app in spec.secret_name
    for doc in docs:
        assert doc["metadata"]["name"] == name
        assert doc["metadata"]["namespace"] == app

    # The Job is a wave-2 Sync hook running as its own ServiceAccount.
    job = next(d for d in docs if d["kind"] == "Job")
    ann = job["metadata"]["annotations"]
    assert ann["argocd.argoproj.io/hook"] == "Sync"
    assert ann["argocd.argoproj.io/sync-wave"] == "2"
    assert ann["argocd.argoproj.io/hook-delete-policy"] == "BeforeHookCreation"
    assert job["spec"]["template"]["spec"]["serviceAccountName"] == name

    # RBAC: create unscoped (create cannot take resourceNames), get+patch scoped
    # to exactly this Secret (the guard + the annotation convergence).
    role = next(d for d in docs if d["kind"] == "Role")
    by_verbs = {tuple(rule["verbs"]): rule for rule in role["rules"]}
    assert ("create",) in by_verbs and "resourceNames" not in by_verbs[("create",)]
    scoped = by_verbs[("get", "patch")]
    assert scoped["resourceNames"] == [spec.secret_name]

    # The script generates-if-absent (guard + else arm) and never blind-rotates.
    script = job["spec"]["template"]["spec"]["containers"][0]["command"][-1]
    assert f"kubectl get secret {spec.secret_name}" in script
    assert f"kubectl create secret generic {spec.secret_name}" in script
    # Every random value is minted from /dev/urandom into a variable (busybox
    # od/base64, never openssl: the kubectl image does not carry it) and never
    # echoed.
    for key, _encoding, nbytes in spec.random_keys:
        assert f"head -c {nbytes} /dev/urandom" in script
        assert "openssl" not in script
        assert f'--from-literal={key}="$' in script


@intent("INT-GRANT-003")
@pytest.mark.parametrize("app", APPS)
@pytest.mark.parametrize("make_spec", [pg_app_secret, keycloak_secret])
def test_reflection_converges_on_every_run(app: str, make_spec) -> None:
    """The annotate step runs outside the create-if-absent guard, with
    --overwrite: a Job that died between create and annotate must heal on the
    next sync rather than strand an unreflected credential the provisioning Job
    would wait on forever."""
    spec = make_spec(app)
    script = _job_script(render_secret_generator(app, spec))
    annotate_at = script.index(f"kubectl annotate secret {spec.secret_name}")
    assert script.index("\nfi") < annotate_at, "annotate must sit after the guard closes"
    assert "--overwrite" in script
    assert f"reflection-auto-namespaces={spec.reflect_namespace}" in script
    assert f"reflection-allowed-namespaces={spec.reflect_namespace}" in script


def test_pg_app_is_basic_auth_with_the_app_as_username_and_a_dsn_safe_password() -> None:
    script = _job_script(render_secret_generator("scrapyard", pg_app_secret("scrapyard")))
    assert "--type=kubernetes.io/basic-auth" in script
    assert "--from-literal=username=scrapyard" in script
    # Hex, not base64: a password that lands in a DSN must not carry +/=.
    assert "head -c 24 /dev/urandom | od -An -tx1" in script
    assert "reflection-auto-namespaces=databases" in script


def test_keycloak_mints_the_three_realm_keys_and_a_32_char_cookie() -> None:
    script = _job_script(render_secret_generator("scrapyard", keycloak_secret("scrapyard")))
    for key in ("clientSecret", "cookieSecret", "realmAdminPassword"):
        assert f'--from-literal={key}="$' in script
    # oauth2-proxy consumes the cookie secret's raw string bytes as its AES key:
    # exactly 16/24/32 CHARACTERS. hex 16 = 32 chars; a standard base64 value is
    # 44 chars and crash-loops the sidecar (see the onboard-a-realm guide).
    assert "head -c 16 /dev/urandom | od -An -tx1" in script
    assert "base64" not in script
    assert "reflection-auto-namespaces=identity" in script


def test_in_place_runtime_secret_carries_no_reflector_annotation() -> None:
    """A Class 3a secret stays in its namespace: no reflector annotation may
    appear anywhere in the block, or a runtime secret would leak into a shared
    namespace."""
    block = render_secret_generator("scrapyard", _runtime_auth_secret("scrapyard"))
    assert "reflector.v1.k8s.emberstack.com" not in block
    assert "kubectl annotate" not in _job_script(block)


def test_self_consistency_fails_closed_on_a_shared_credential_name() -> None:
    """A credential name that is not per-app would let one app provision against
    another's credential; the gate must reject it rather than render it."""
    shared = GeneratedSecret(
        secret_name="pg-app",  # the shared name, not pg-app-<app>
        secret_type="kubernetes.io/basic-auth",
        literals=(("username", "intruder"),),
        random_keys=(("password", "hex", 24),),
        reflect_namespace="databases",
    )
    with pytest.raises(ValueError, match="self-consistent"):
        render_secret_generator("intruder", shared)


def test_self_consistency_fails_closed_on_an_unknown_reflection_target() -> None:
    """Reflection targets are exactly the two provisioning namespaces; anything
    else (a typo, another app's namespace) is refused."""
    rogue = GeneratedSecret(
        secret_name="pg-app-intruder",
        secret_type="kubernetes.io/basic-auth",
        literals=(),
        random_keys=(("password", "hex", 24),),
        reflect_namespace="kube-system",
    )
    with pytest.raises(ValueError, match="self-consistent"):
        render_secret_generator("intruder", rogue)


def _job_script(block: str) -> str:
    job = next(
        d
        for d in yaml.safe_load_all(block)
        if d is not None and d["kind"] == "Job"
    )
    return job["spec"]["template"]["spec"]["containers"][0]["command"][-1]
