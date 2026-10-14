"""Render an in-cluster generate-if-absent Job for an app-owned credential.

The platform provisions two per-app credentials against shared resources: the
Postgres role password (``pg-app-<app>``, consumed by the database provisioning
Job in ``database_grant.py``) and the Keycloak realm credential (``keycloak-<app>``,
consumed by the realm provisioning Job in ``identity_grant.py``). Apps also carry
runtime secrets of their own (machine-door Basic credentials, signing keys) that
are pure random values. Historically each app *generated all of these itself* in
its own repo (a ``devops/secrets/generate-secrets.py`` run) and applied them by
hand into its namespace; the per-app credentials then auto-reflected into
``databases`` / ``identity`` for the provisioning Jobs to read. That hand-applied
step is the one thing an autonomous delivery cannot do: an Argo Workflow has no
local shell, no tunnel, no operator.

This module renders the Job that does the generation *in the cluster* instead.
It is the value-creation counterpart of the provisioning Jobs: they *consume* a
credential to cut a role or a realm; this *mints* it. The rules that make it safe:

- **Generate-if-absent, never rotate.** The Job creates the Secret only when it
  is missing, so re-running it (a re-sync, a re-drive, a migration onto an app
  whose credential already exists) never changes a live value.
- **Convergent, not one-shot.** The reflector annotations are applied on every
  run (``kubectl annotate --overwrite``), after the create-if-absent guard. A Job
  that died between create and annotate therefore heals on the next sync instead
  of stranding an unreflected credential the provisioning Job would wait on
  forever.
- **The platform holds no value.** Values are minted inside the app's own
  namespace from ``/dev/urandom`` (busybox-native ``od``/``base64``, no openssl:
  the kubectl image does not carry it, and only the mint arm would discover
  that) and live only there and in the reflected copy; nothing is written to git
  and the platform never reads a value back. Random values are hex by default so
  they are safe in DSNs and URLs; the oauth2-proxy ``cookieSecret`` is 32 hex
  characters (16 bytes), because oauth2-proxy uses the string's raw bytes as its
  AES key (16/24/32 characters exactly; a standard base64 value is the wrong
  length and crash-loops the sidecar).
- **Per-app credential name.** The Secret is named for the app (``pg-app-<app>``,
  ``keycloak-<app>``), never a shared name, so one app's generator can never
  provision against another app's credential (INT-FOUNDRY-040,
  sabbito-bazarrito#7).
- **Reflect to exactly one namespace, or none.** A platform-provisioned
  credential (Class 2) reflects into the one namespace whose provisioning Job
  consumes it. An app runtime secret (Class 3a) stays in place: it renders with
  no reflector annotations at all.

Ordering (the team manifest applies as one ArgoCD sync): the app Namespace is a
normal wave-0 resource; the generator's ServiceAccount/Role/RoleBinding are
normal wave-1 resources; the Job is a wave-2 ``Sync`` hook (a hook, not a tracked
resource, because a Job's generated ``spec.selector`` is immutable and
self-heal's ``kubectl replace`` would be rejected). The PostSync provisioning Job
runs after the whole sync and already waits for the reflected credential, so
reflection lag between this Job and that one is tolerated.

Every ``<app>`` token is substituted by ``render_secret_generator``; the result
is validated self-consistent before it is returned, so a template regression
fails closed here rather than shipping a manifest the platform's isolation suite
rejects.
"""

# The shell lines of the embedded Job template legitimately exceed the line length;
# disable E501 for this file (the Python below stays within it).
# ruff: noqa: E501

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "APP_PLACEHOLDER",
    "GeneratedSecret",
    "pg_app_secret",
    "keycloak_secret",
    "render_secret_generator",
    "secret_generator_is_self_consistent",
]

APP_PLACEHOLDER = "<app>"

# An image carrying kubectl and a POSIX shell (randomness comes from
# /dev/urandom + busybox od/base64; the image carries no openssl and none is
# needed). alpine/k8s is a small public image; the cluster already pulls other
# public images (postgres, keycloak-config-cli) the same way.
_IMAGE = "alpine/k8s:1.31.1"

# The emberstack reflector annotation prefix (ADR-016). Applied to a generated
# Class 2 credential so its reflected copy appears exactly as a hand-applied
# credential's would; never applied to an in-place Class 3a secret.
_REFLECTOR_PREFIX = "reflector.v1.k8s.emberstack.com"

_RANDOM_ENCODINGS = frozenset({"hex", "base64"})


@dataclass(frozen=True)
class GeneratedSecret:
    """A credential the platform generates in-cluster if it is absent.

    ``secret_name`` is the per-app Secret name (it must contain the app name).
    ``secret_type`` is the Kubernetes Secret type, or ``None`` for ``Opaque``.
    ``literals`` are fixed key/value pairs (e.g. the username). ``random_keys``
    are ``(key, encoding, byte_length)`` triples: ``byte_length`` bytes of
    ``/dev/urandom`` rendered as hex or base64 with busybox-native tools; hex is
    the default choice because it is safe inside DSNs and URLs.
    ``reflect_namespace`` is the one namespace the credential auto-reflects into
    (Class 2), or ``None`` for an in-place app runtime secret (Class 3a).
    """

    secret_name: str
    secret_type: str | None
    literals: tuple[tuple[str, str], ...]
    random_keys: tuple[tuple[str, str, int], ...]
    reflect_namespace: str | None


def pg_app_secret(app: str) -> GeneratedSecret:
    """The Postgres role credential the database provisioning Job consumes.

    Basic-auth (username + password); the username is the app, the password is
    a random 24-byte hex value (DSN-safe); reflects into ``databases``.
    """
    return GeneratedSecret(
        secret_name=f"pg-app-{app}",
        secret_type="kubernetes.io/basic-auth",
        literals=(("username", app),),
        random_keys=(("password", "hex", 24),),
        reflect_namespace="databases",
    )


def keycloak_secret(app: str) -> GeneratedSecret:
    """The Keycloak realm credential the realm provisioning Job and the app's
    oauth2-proxy consume.

    Opaque, three random keys: the OIDC ``clientSecret`` (hex), the oauth2-proxy
    ``cookieSecret`` (32 hex characters: oauth2-proxy consumes the raw string
    bytes as its AES key, so the length must be exactly 16/24/32 characters and
    a standard base64 value crash-loops the sidecar), and the
    ``realmAdminPassword`` (hex); reflects into ``identity``.
    """
    return GeneratedSecret(
        secret_name=f"keycloak-{app}",
        secret_type=None,
        literals=(),
        random_keys=(
            ("clientSecret", "hex", 24),
            ("cookieSecret", "hex", 16),
            ("realmAdminPassword", "hex", 24),
        ),
        reflect_namespace="identity",
    )


def _shell_var(key: str) -> str:
    """A shell variable name for a Secret key (upper-cased letters/digits)."""
    return "".join(ch if ch.isalnum() else "_" for ch in key).upper()


def _generate_script(app: str, spec: GeneratedSecret) -> str:
    """The generate-if-absent shell script, indented for a YAML block scalar.

    Shape: create only when absent; converge the reflector annotations on every
    run (so a run that died mid-way heals on the next sync); never echo a value.
    """
    lines: list[str] = [
        "set -eu",
        f"if kubectl get secret {spec.secret_name} -n {app} >/dev/null 2>&1; then",
        f'  echo "{spec.secret_name} present; leaving value as is (generate-if-absent, never rotate)"',
        "else",
        f'  echo "generating {spec.secret_name}"',
    ]
    # Mint each random value into a shell variable first, so it is never echoed.
    # /dev/urandom + busybox od/base64, never openssl: the kubectl image does not
    # carry it, and only the mint arm would discover that (the guard arm passed
    # every test that never exercised a fresh mint).
    for key, encoding, nbytes in spec.random_keys:
        if encoding == "hex":
            mint = f"head -c {nbytes} /dev/urandom | od -An -tx1 | tr -d ' \\n'"
        else:
            mint = f"head -c {nbytes} /dev/urandom | base64 | tr -d '\\n'"
        lines.append(f'  {_shell_var(key)}="$({mint})"')

    create = [f"  kubectl create secret generic {spec.secret_name} -n {app}"]
    if spec.secret_type is not None:
        create.append(f"--type={spec.secret_type}")
    for key, value in spec.literals:
        create.append(f"--from-literal={key}={value}")
    for key, _encoding, _nbytes in spec.random_keys:
        create.append(f'--from-literal={key}="${_shell_var(key)}"')
    # One logical command across continued lines, indented inside the else arm.
    lines.append(" \\\n    ".join(create))
    lines.append("fi")

    if spec.reflect_namespace is not None:
        annotate = [f"kubectl annotate secret {spec.secret_name} -n {app} --overwrite"]
        for suffix, value in (
            ("reflection-allowed", "true"),
            ("reflection-allowed-namespaces", spec.reflect_namespace),
            ("reflection-auto-enabled", "true"),
            ("reflection-auto-namespaces", spec.reflect_namespace),
        ):
            annotate.append(f"{_REFLECTOR_PREFIX}/{suffix}={value}")
        lines.append(" \\\n  ".join(annotate))
        lines.append(f'echo "{spec.secret_name} reflection converged into {spec.reflect_namespace}"')
    else:
        lines.append(f'echo "{spec.secret_name} ready in place"')

    # Indent every physical line (including continuations) to 14 spaces for the
    # block scalar under `- |`.
    indent = " " * 14
    return "\n".join(indent + line for line in "\n".join(lines).split("\n"))


def render_secret_generator(app: str, spec: GeneratedSecret) -> str:
    """The generate-if-absent block (ServiceAccount, Role, RoleBinding, Job) for
    ``app``'s ``spec`` credential. No leading ``---``; the manifest appender adds
    the document separator. Validated self-consistent before return."""
    name = f"gen-{spec.secret_name}"
    script = _generate_script(app, spec)
    travel = (
        f"auto-reflects into {spec.reflect_namespace} exactly as a hand-applied credential would"
        if spec.reflect_namespace is not None
        else "stays in this namespace (an app runtime secret; nothing else reads it)"
    )
    block = f"""# In-cluster generation of the app-owned {spec.secret_name} credential (platform ADR-034).
# The platform mints it here only if it is absent, so onboarding needs no app-side
# secret script and no local apply-secrets run: an Argo Workflow delivery is
# sufficient. Generate-if-absent, so a re-run never rotates a live credential; the
# reflector annotations converge on every run, so a run that died mid-way heals on
# the next sync. The value is created in the app's own namespace and {travel};
# the platform holds no copy. RBAC is normal (wave 1); the Job is a wave-2 Sync
# hook (a Job cannot be a tracked resource: its immutable spec.selector breaks
# self-heal's replace).
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {name}
  namespace: {app}
  annotations:
    argocd.argoproj.io/sync-wave: "1"
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: {name}
  namespace: {app}
  annotations:
    argocd.argoproj.io/sync-wave: "1"
rules:
  # Create the Secret (create cannot be scoped to a resourceName)...
  - apiGroups: [""]
    resources: [secrets]
    verbs: [create]
  # ...and read/patch only this one (the existence guard + annotation convergence).
  - apiGroups: [""]
    resources: [secrets]
    resourceNames: ["{spec.secret_name}"]
    verbs: [get, patch]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: {name}
  namespace: {app}
  annotations:
    argocd.argoproj.io/sync-wave: "1"
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: {name}
subjects:
  - kind: ServiceAccount
    name: {name}
    namespace: {app}
---
apiVersion: batch/v1
kind: Job
metadata:
  name: {name}
  namespace: {app}
  annotations:
    # Sync hook after the wave-1 RBAC, before the PostSync provisioning Job that
    # reads the reflected credential; BeforeHookCreation clears the prior run.
    argocd.argoproj.io/hook: Sync
    argocd.argoproj.io/sync-wave: "2"
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation
spec:
  backoffLimit: 6
  activeDeadlineSeconds: 300
  template:
    spec:
      serviceAccountName: {name}
      restartPolicy: OnFailure
      containers:
        - name: generate
          image: {_IMAGE}
          command:
            - /bin/sh
            - -c
            - |
{script}"""
    if not secret_generator_is_self_consistent(block_text=block, app=app, spec=spec):
        raise ValueError(
            "the secret-generator template did not render self-consistent for "
            f"{app!r}/{spec.secret_name!r}; the template is broken"
        )
    return block


def secret_generator_is_self_consistent(*, block_text: str, app: str, spec: GeneratedSecret) -> bool:
    """The generated block mints a per-app credential safely: no placeholder
    survives, the Secret is named for the app, generation is guarded by an
    existence check (never a blind rotate), a Class 2 credential converges its
    reflection into exactly one target namespace on every run, and a Class 3a
    secret carries no reflector annotation at all."""
    if APP_PLACEHOLDER in block_text:
        return False
    if app not in spec.secret_name:
        # A per-app credential name is the isolation invariant; a shared name
        # would let one app provision against another app's credential.
        return False
    if spec.reflect_namespace not in {None, "databases", "identity"}:
        return False
    if any(encoding not in _RANDOM_ENCODINGS for _key, encoding, _n in spec.random_keys):
        return False
    required = (
        f"name: gen-{spec.secret_name}",
        f"kubectl get secret {spec.secret_name}",           # the generate-if-absent guard
        f"kubectl create secret generic {spec.secret_name}",
        "argocd.argoproj.io/hook: Sync",
    )
    if not all(token in block_text for token in required):
        return False
    if spec.reflect_namespace is None:
        return _REFLECTOR_PREFIX not in block_text
    return (
        f"kubectl annotate secret {spec.secret_name}" in block_text
        and "--overwrite" in block_text
        and f"{_REFLECTOR_PREFIX}/reflection-auto-namespaces={spec.reflect_namespace}" in block_text
    )
