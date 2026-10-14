"""Render an app's event-bus grant: mint its own key, get a scoped user JWT back.

The bus (foundry-platform ADR-041) is one shared NATS instance whose ``EVENTS``
account owns the whole ``com.foundry.>`` subject space. An app is admitted to it
by being signed a NATS *user* in that account, whose permissions are fixed in the
JWT at signing time: publish only under the domains it owns, subscribe across the
whole event space, and drive durable consumers on the one shared stream. The
server enforces those on every message, so an app cannot publish as another app
by misconfiguration or by choosing a different subject at runtime.

A user JWT needs no server-side registration, which is the property that lets the
whole grant live in the app's own ``teams/<app>/`` folder: nothing platform-wide
changes per app, and no server restarts. That is the same shape the database
(``database_grant``) and realm (``identity_grant``) grants have.

**The key direction is inverted, and that is the point.** An nkey is a keypair,
so unlike a password the app does not need to hand anything over to be
provisioned. The app mints its own seed in its own namespace and publishes only
the derived PUBLIC key; the platform signs an assertion about a key it has never
seen. The private seed never leaves the app's namespace and is never reflected,
so this grant is strictly tighter than the two before it, where a platform-side
Job reads a reflected app password.

Three steps, and each is one tool doing one thing:

1. ``gen-nats-<app>`` (app namespace, wave-2 Sync hook) mints the keypair and
   writes TWO secrets: ``nats-<app>`` holding the seed, with no reflector
   annotation at all, and ``nats-<app>-pub`` holding only the public key, set to
   auto-reflect into ``messaging``. Two secrets rather than two keys in one,
   because reflecting one secret would carry the seed with it, which is the whole
   property this grant exists to keep.
2. ``nats-sign-<app>`` (``messaging``, PostSync) waits for the reflected public
   key, builds a throwaway nsc store from the seeded signer material, signs the
   scoped user JWT, and stores it as ``nats-jwt-<app>`` set to auto-reflect back
   into the app's namespace. A JWT is not secret, so it travels as ordinary
   reflected material and no cross-namespace write RBAC is needed anywhere.
3. The app connects with its own seed plus the reflected JWT.

Image split: ``nk``/``nsc`` live in ``nats-box`` and ``kubectl`` lives in
``alpine/k8s``, and neither carries the other, so each Job is an initContainer
chain that hands work along an ``emptyDir``. The mint always runs and the CREATE
is guarded, so a re-run never rotates a live seed (platform ADR-034's rule); a minted but
unused keypair dies with the pod.

Every ``<app>`` token is substituted by ``render_events_grant``; the result is
validated self-consistent before it is returned, so a template regression fails
closed here rather than shipping a manifest the platform's isolation suite
rejects.
"""

# The shell lines of the embedded Job templates legitimately exceed the line
# length; disable E501 for this file (the Python below stays within it).
# ruff: noqa: E501

from __future__ import annotations

import re

__all__ = [
    "APP_PLACEHOLDER",
    "DOMAIN_PATTERN",
    "EVENTS_NAMESPACE",
    "STREAM",
    "events_grant_is_self_consistent",
    "normalise_domains",
    "render_events_grant",
]

APP_PLACEHOLDER = "<app>"

# The namespace the shared bus runs in, and the one stream it serves.
EVENTS_NAMESPACE = "messaging"
STREAM = "FOUNDRY_EVENTS"

# The seeded material a signing Job mounts: the two public JWTs plus the EVENTS
# account signing key. Deliberately NOT the server's own `nats-auth`, which
# carries no signing key and is mounted by the NATS pod and the stream Job.
SIGNER_SECRET = "nats-events-signer"

# nk and nsc; the same image the stream-provisioning Job in the platform chart
# uses, so the fleet pins one NATS toolchain.
_NATS_IMAGE = "natsio/nats-box:0.19.7"
# kubectl and a POSIX shell, as the credential generators already use.
_KUBECTL_IMAGE = "alpine/k8s:1.31.1"

_REFLECTOR_PREFIX = "reflector.v1.k8s.emberstack.com"

# A REF-Events domain segment: the bounded area a fact belongs to, never the app
# that emitted it. One owner per domain, which INT-FOUNDRY-066 holds across an
# install's teams.
DOMAIN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def normalise_domains(domains: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """The domains this app may publish under, cleaned and ordered.

    Raises ``ValueError`` when the set is empty or a segment is not a valid
    domain. An empty set is refused rather than defaulted: a grant that scoped
    publishing to nothing would admit an app to the bus as a reader while
    looking like a producer grant, and one that defaulted to the app's own name
    would quietly mint a domain the type registry never agreed to.
    """
    seen: list[str] = []
    for raw in domains:
        domain = str(raw).strip().lower()
        if not DOMAIN_PATTERN.match(domain):
            raise ValueError(
                f"{raw!r} is not a REF-Events domain segment: expected lower-case "
                "letters, digits and dashes, for example 'platform' or 'delivery'"
            )
        if domain not in seen:
            seen.append(domain)
    if not seen:
        raise ValueError(
            "an events grant must name at least one domain the app publishes "
            "under; publishing is owned per domain (REF-Events section 4)"
        )
    return tuple(seen)


def _permissions(domains: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The (publish, subscribe) subject allow-lists for the app's user JWT."""
    publish = [f"com.foundry.{domain}.>" for domain in domains]
    publish += [
        # Read the one shared stream's shape, and drive consumers on it. Scoped
        # to the stream by name: `$JS.API.>` would hand an app the whole
        # JetStream control plane. Consumer NAMES cannot be scoped per app (a
        # NATS wildcard matches a whole token, never a prefix within one), which
        # platform ADR-041 decision 3 records as the one convention-bound edge here.
        f"$JS.API.STREAM.INFO.{STREAM}",
        f"$JS.API.CONSUMER.*.{STREAM}",
        f"$JS.API.CONSUMER.*.{STREAM}.>",
        f"$JS.API.CONSUMER.*.*.{STREAM}.>",
        f"$JS.ACK.{STREAM}.>",
    ]
    # Reading is open across the whole event space: REF-Events section 8 says any
    # app may subscribe to any type, and a consumer that had to be granted each
    # domain is the hand-wired webhook the bus exists to replace.
    subscribe = ["com.foundry.>", "_INBOX.>"]
    return tuple(publish), tuple(subscribe)


def _indent(text: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(pad + line if line else line for line in text.split("\n"))


def _mint_script(app: str) -> str:
    """Mint the keypair into the shared emptyDir (nats-box: nk)."""
    return "\n".join(
        [
            "set -eu",
            "# An nkey is an ed25519 keypair, not a random string, so this mints with",
            "# nk rather than the /dev/urandom shape the password generators use.",
            "nk -gen user > /work/seed",
            "nk -inkey /work/seed -pubout > /work/public",
            'echo "minted a user keypair (public key only is ever published)"',
        ]
    )


def _store_script(app: str) -> str:
    """Create the two secrets, guarding the seed (kubectl)."""
    return "\n".join(
        [
            "set -eu",
            f"if kubectl get secret nats-{app} -n {app} >/dev/null 2>&1; then",
            f'  echo "nats-{app} present; leaving the seed as is (generate-if-absent, never rotate)"',
            "else",
            f'  echo "storing the minted keypair for {app}"',
            f"  kubectl create secret generic nats-{app} -n {app} \\",
            '    --from-file=seed=/work/seed \\',
            '    --from-file=public=/work/public',
            "fi",
            "# The public half travels; the seed never does. Separate secrets, because",
            "# reflecting one secret would carry the seed with it.",
            f"kubectl create secret generic nats-{app}-pub -n {app} \\",
            f"  --from-literal=public=\"$(kubectl get secret nats-{app} -n {app} -o jsonpath='{{.data.public}}' | base64 -d)\" \\",
            "  --dry-run=client -o yaml | kubectl apply -f -",
            f"kubectl annotate secret nats-{app}-pub -n {app} --overwrite \\",
            f"  {_REFLECTOR_PREFIX}/reflection-allowed=true \\",
            f"  {_REFLECTOR_PREFIX}/reflection-allowed-namespaces={EVENTS_NAMESPACE} \\",
            f"  {_REFLECTOR_PREFIX}/reflection-auto-enabled=true \\",
            f"  {_REFLECTOR_PREFIX}/reflection-auto-namespaces={EVENTS_NAMESPACE}",
            f'echo "nats-{app}-pub reflection converged into {EVENTS_NAMESPACE}"',
        ]
    )


def _fetch_script(app: str) -> str:
    """Wait for the reflected public key (kubectl)."""
    return "\n".join(
        [
            "set -eu",
            f"until kubectl get secret nats-{app}-pub -n {EVENTS_NAMESPACE} >/dev/null 2>&1; do",
            f'  echo "waiting for the reflected public key of {app}"; sleep 5',
            "done",
            f"kubectl get secret nats-{app}-pub -n {EVENTS_NAMESPACE} -o jsonpath='{{.data.public}}' | base64 -d > /work/public",
            'test -s /work/public',
            'echo "read the app public key: $(cat /work/public)"',
        ]
    )


def _sign_script(app: str, domains: tuple[str, ...]) -> str:
    """Build a throwaway nsc store and sign the scoped user JWT (nats-box)."""
    publish, subscribe = _permissions(domains)
    # Every allow line keeps its continuation: the redirect below closes the
    # one logical command, so stripping the last backslash would orphan it into
    # a bare redirect that suppresses nothing.
    allow = [f"  --allow-pub '{subject}' \\" for subject in publish]
    allow += [f"  --allow-sub '{subject}' \\" for subject in subscribe]
    return "\n".join(
        [
            "set -eu",
            "# A throwaway store, built from the seeded material and thrown away with",
            "# the pod. The signer secret is copied to a clean directory first: a",
            "# Kubernetes secret mount carries ..data symlinks that a directory import",
            "# would walk twice.",
            "export XDG_DATA_HOME=/tmp/store XDG_CONFIG_HOME=/tmp/config NKEYS_PATH=/tmp/keys",
            "mkdir -p /tmp/sk /tmp/store /tmp/config /tmp/keys",
            "cp /var/run/signer/events-signer.nk /tmp/sk/",
            "nsc add operator --url /var/run/signer/operator.jwt >/dev/null",
            "nsc import account --file /var/run/signer/events.jwt >/dev/null",
            "nsc import keys --dir /tmp/sk >/dev/null",
            "# Sign for the PUBLIC key only: --public-key leaves no seed in the keyring,",
            "# because there is no seed here to leave. Re-signing is idempotent in effect;",
            "# the store is fresh every run, so the user is always added, never edited.",
            f"nsc add user --account EVENTS --name {app} \\",
            '  --public-key "$(cat /work/public)" \\',
            *allow,
            "  >/dev/null",
            f"nsc describe user --account EVENTS --name {app} --raw | tr -d '\\n' > /work/user.jwt",
            "test -s /work/user.jwt",
            f'echo "signed a user JWT for {app}, scoped to {" ".join(domains)}"',
        ]
    )


def _publish_script(app: str) -> str:
    """Store the JWT, set to reflect back into the app's namespace (kubectl)."""
    return "\n".join(
        [
            "set -eu",
            "# Converge rather than guard: a JWT is not secret and carries no state, so",
            "# re-signing on a permission change is the intended way to move an app's",
            "# scope. The seed it pairs with is what must never be rotated.",
            f"kubectl create secret generic nats-jwt-{app} -n {EVENTS_NAMESPACE} \\",
            "  --from-file=user.jwt=/work/user.jwt \\",
            "  --dry-run=client -o yaml | kubectl apply -f -",
            f"kubectl annotate secret nats-jwt-{app} -n {EVENTS_NAMESPACE} --overwrite \\",
            f"  {_REFLECTOR_PREFIX}/reflection-allowed=true \\",
            f"  {_REFLECTOR_PREFIX}/reflection-allowed-namespaces={app} \\",
            f"  {_REFLECTOR_PREFIX}/reflection-auto-enabled=true \\",
            f"  {_REFLECTOR_PREFIX}/reflection-auto-namespaces={app}",
            f'echo "nats-jwt-{app} reflection converged back into {app}"',
        ]
    )


def render_events_grant(app: str, domains: tuple[str, ...] | list[str]) -> str:
    """The event-bus grant block for ``app``, publishing under ``domains``.

    No leading ``---``; the manifest appender adds the document separator.
    Validated self-consistent before return.
    """
    owned = normalise_domains(domains)
    scope = ", ".join(f"com.foundry.{domain}.>" for domain in owned)
    block = f"""# Event-bus access for {app} (platform ADR-041): a NATS user in the shared EVENTS account,
# signed to publish {scope} and nothing else. Reading is open across
# com.foundry.> because REF-Events section 8 restricts speaking, not listening.
#
# The app mints its own keypair here and publishes only the PUBLIC half; the seed
# never leaves this namespace and is never reflected. The platform signs an
# assertion about a key it has never seen, so unlike the database and realm
# grants there is no tenant secret for it to read.
apiVersion: v1
kind: ServiceAccount
metadata:
  name: gen-nats-{app}
  namespace: {app}
  annotations:
    argocd.argoproj.io/sync-wave: "1"
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: gen-nats-{app}
  namespace: {app}
  annotations:
    argocd.argoproj.io/sync-wave: "1"
rules:
  # Create the secrets (create cannot be scoped to a resourceName)...
  - apiGroups: [""]
    resources: [secrets]
    verbs: [create]
  # ...and read/patch only this app's own two.
  - apiGroups: [""]
    resources: [secrets]
    resourceNames: ["nats-{app}", "nats-{app}-pub"]
    verbs: [get, patch]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: gen-nats-{app}
  namespace: {app}
  annotations:
    argocd.argoproj.io/sync-wave: "1"
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: gen-nats-{app}
subjects:
  - kind: ServiceAccount
    name: gen-nats-{app}
    namespace: {app}
---
apiVersion: batch/v1
kind: Job
metadata:
  name: gen-nats-{app}
  namespace: {app}
  annotations:
    argocd.argoproj.io/hook: Sync
    argocd.argoproj.io/sync-wave: "2"
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation
spec:
  backoffLimit: 6
  activeDeadlineSeconds: 300
  template:
    spec:
      serviceAccountName: gen-nats-{app}
      restartPolicy: OnFailure
      volumes:
        - name: work
          emptyDir: {{}}
      initContainers:
        # nk lives in nats-box, kubectl in alpine/k8s, and neither carries the
        # other; the keypair is handed along an emptyDir that dies with the pod.
        - name: mint
          image: {_NATS_IMAGE}
          command:
            - /bin/sh
            - -c
            - |
{_indent(_mint_script(app), 14)}
          volumeMounts:
            - name: work
              mountPath: /work
      containers:
        - name: store
          image: {_KUBECTL_IMAGE}
          command:
            - /bin/sh
            - -c
            - |
{_indent(_store_script(app), 14)}
          volumeMounts:
            - name: work
              mountPath: /work
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: nats-sign-{app}
  namespace: {EVENTS_NAMESPACE}
  annotations:
    argocd.argoproj.io/sync-wave: "1"
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: nats-sign-{app}
  namespace: {EVENTS_NAMESPACE}
  annotations:
    argocd.argoproj.io/sync-wave: "1"
rules:
  - apiGroups: [""]
    resources: [secrets]
    verbs: [create]
  # Read only this app's reflected public key, and manage only its JWT. The
  # seeded signer material is mounted as a volume, never read through the API.
  - apiGroups: [""]
    resources: [secrets]
    resourceNames: ["nats-{app}-pub", "nats-jwt-{app}"]
    verbs: [get, patch]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: nats-sign-{app}
  namespace: {EVENTS_NAMESPACE}
  annotations:
    argocd.argoproj.io/sync-wave: "1"
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: nats-sign-{app}
subjects:
  - kind: ServiceAccount
    name: nats-sign-{app}
    namespace: {EVENTS_NAMESPACE}
---
apiVersion: batch/v1
kind: Job
metadata:
  name: nats-sign-{app}
  namespace: {EVENTS_NAMESPACE}
  annotations:
    # PostSync, so it runs after the app's own generator has minted and the
    # reflector has carried the public key over; it waits for it regardless.
    argocd.argoproj.io/hook: PostSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation
spec:
  backoffLimit: 6
  activeDeadlineSeconds: 600
  template:
    spec:
      serviceAccountName: nats-sign-{app}
      restartPolicy: OnFailure
      volumes:
        - name: work
          emptyDir: {{}}
        - name: signer
          secret:
            secretName: {SIGNER_SECRET}
      initContainers:
        - name: fetch
          image: {_KUBECTL_IMAGE}
          command:
            - /bin/sh
            - -c
            - |
{_indent(_fetch_script(app), 14)}
          volumeMounts:
            - name: work
              mountPath: /work
        - name: sign
          image: {_NATS_IMAGE}
          command:
            - /bin/sh
            - -c
            - |
{_indent(_sign_script(app, owned), 14)}
          volumeMounts:
            - name: work
              mountPath: /work
            - name: signer
              mountPath: /var/run/signer
              readOnly: true
      containers:
        - name: publish
          image: {_KUBECTL_IMAGE}
          command:
            - /bin/sh
            - -c
            - |
{_indent(_publish_script(app), 14)}
          volumeMounts:
            - name: work
              mountPath: /work"""
    if not events_grant_is_self_consistent(block_text=block, app=app, domains=owned):
        raise ValueError(
            "the events-grant template did not render self-consistent for "
            f"{app!r}/{owned!r}; the template is broken"
        )
    return block


def events_grant_is_self_consistent(
    *, block_text: str, app: str, domains: tuple[str, ...]
) -> bool:
    """The rendered grant keeps the properties that make it safe.

    No placeholder survives; the seed secret carries no reflector annotation of
    any kind; only the public key reflects, into exactly ``messaging``; the JWT
    reflects back into exactly the app's namespace; the signer material is
    mounted only by the signing Job; and the publish scope is the app's declared
    domains and the one shared stream's API, never the whole JetStream surface.
    """
    if APP_PLACEHOLDER in block_text:
        return False
    # The seed's own secret must never be told to reflect anywhere. Checked on
    # the annotate call, which is the only thing that could grant it travel.
    if f"kubectl annotate secret nats-{app} -n {app}" in block_text:
        return False
    for suffix in ("reflection-auto-namespaces", "reflection-allowed-namespaces"):
        if f"{_REFLECTOR_PREFIX}/{suffix}={EVENTS_NAMESPACE}" not in block_text:
            return False
        if f"{_REFLECTOR_PREFIX}/{suffix}={app}" not in block_text:
            return False
    # The signer material reaches exactly one Job.
    if block_text.count(f"secretName: {SIGNER_SECRET}") != 1:
        return False
    # Publishing is scoped: every declared domain, and no blanket JetStream API.
    for domain in domains:
        if f"--allow-pub 'com.foundry.{domain}.>'" not in block_text:
            return False
    if "--allow-pub '$JS.API.>'" in block_text:
        return False
    # Reading is open, which is the contract, not an oversight.
    return "--allow-sub 'com.foundry.>'" in block_text
