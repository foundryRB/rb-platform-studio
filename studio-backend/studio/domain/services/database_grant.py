"""Render an app's database provisioning Job from one canonical template.

Every part of a team folder is rendered from a studio-owned template: the
skeleton (namespace, Gateway, RBAC, Application, docs route) from ``team_skeleton``
(INT-SKELETON-001), the realm from ``identity_grant``, and the database
provisioning Job from the template below. None is copied from a donor app. The
Job especially is not identity boilerplate: it is a
procedure whose correctness (a per-app ``pg-app-<app>`` credential name, the PG16
``GRANT <app> TO CURRENT_USER WITH SET TRUE`` self-grant, ownership, the connect
lockdown) has nothing to do with the app's name. Copying a live app's Job and
substituting the name therefore cannot guarantee those invariants -- it only
carries them when the reference already happens to be clean, and silently drops
them when it is not. Pointing the old ``STUDIO_REFERENCE_DB_APP`` at solveos (the
first onboarded database app, which legitimately owns the bare ``pg-app`` name and
predates the SET-role grant) reproduced both bugs in every mirror
(sabbito-bazarrito#7). So the studio owns the one canonical Job itself and fills in
the app name, rather than outsourcing it to whichever neighbour it is pointed at.

Every ``<app>`` token below is intentional and substituted by ``render_database_job``.
The block is the same one documented as the by-hand runbook in the platform repo
(``guides/onboard-a-database.md``); the platform's isolation suite
(INT-FOUNDRY-014..041) gates whatever this renders, so correctness never rests on
this template agreeing with the prose.
"""

# The shell/SQL lines of the embedded Job template legitimately exceed the line
# length; disable E501 for this file (the Python below stays within it).
# ruff: noqa: E501

from __future__ import annotations

from studio.domain.services.team_documents import database_job_is_isolation_clean

__all__ = ["APP_PLACEHOLDER", "render_database_job"]

APP_PLACEHOLDER = "<app>"

# The canonical provisioning Job, fully <app>-tokenized. No leading `---`:
# the concern-file appender adds the document separator when it appends this.
_PROVISION_JOB_TEMPLATE = r"""# Database provisioning (platform ADR-026), rendered from the studio's canonical template.
# One idempotent Job creates the <app> database and its least-privilege owner role
# and locks the database down, authenticating as the shared db-provisioner role
# (platform/72-postgres-cluster.yaml). The app's role password lives in the app's
# own namespace as Secret pg-app-<app> (username <app> + password), minted
# in-cluster by the gen-pg-app-<app> generate-if-absent Job (platform ADR-034) and
# AUTO-reflected into the databases namespace as pg-app-<app>, which this Job
# mounts for the ALTER ROLE password. A PER-APP name is used, never the shared
# "pg-app": every app's credential reflects into the databases namespace, so a
# shared name would provision one app's role with another app's password
# (sabbito-bazarrito#7). The reflected copy is reflector-owned (no git stub), so
# platform/ gains nothing per app; no secret value ever enters git and the
# platform never reads one back.
apiVersion: batch/v1
kind: Job
metadata:
  name: pg-<app>-provision
  namespace: databases
  annotations:
    # One-shot job: run it as a sync hook (created/deleted by the hook lifecycle),
    # not a tracked resource. A tracked Job fails self-heal because ArgoCD tries to
    # `kubectl replace` it, but a Job's generated spec.selector is immutable/required,
    # so the replace is rejected. PostSync runs after the namespace and the mirrored
    # credential are applied; BeforeHookCreation deletes the prior run before
    # re-running. Every statement is idempotent, so re-runs converge (they do not
    # change the live password: the ALTER ROLE always sets the same app-owned value).
    argocd.argoproj.io/hook: PostSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation
spec:
  backoffLimit: 6
  activeDeadlineSeconds: 600
  template:
    spec:
      restartPolicy: OnFailure
      containers:
        - name: provision
          image: postgres:17-alpine
          command:
            - /bin/sh
            - -c
            - |
              set -eu
              # The app role password is auto-reflected into this namespace as
              # pg-app-<app> and mounted at /var/run/app-cred. Wait for BOTH the
              # database (as db-provisioner) AND the mirrored password file; the
              # reflector can lag and mounted secrets refresh at runtime, so a single
              # pod waits it out rather than ever setting an empty password on the role.
              until [ -s /var/run/app-cred/password ] && psql -c 'SELECT 1' >/dev/null 2>&1; do
                echo "waiting for db and mirrored app password"; sleep 5
              done
              APP_PASSWORD="$(cat /var/run/app-cred/password)"

              # 1) Role: create <app> if absent via the psql \gexec trick (NOT a DO $$
              #    block, which Kubernetes mangles by collapsing $$ to a single $ in a
              #    container command). Double-quote the identifier so a dashed name is
              #    valid; keep the rolname literal single-quoted in the WHERE clause.
              psql -v ON_ERROR_STOP=1 <<'SQL'
              SELECT 'CREATE ROLE "<app>" LOGIN'
              WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '<app>')\gexec
              SQL

              # Converge attributes + the app-owned password. NOSUPERUSER is intentionally
              # omitted: a non-superuser role may never alter the SUPERUSER attribute (even
              # to set it off, even on a role it owns), and a role this provisioner creates
              # is NOSUPERUSER by default; NOCREATEDB/NOCREATEROLE it can set. If the role
              # pre-exists from an earlier authority (a migration), the provisioner lacks
              # ADMIN on it and this ALTER is refused; that is acceptable only when the role
              # already matches the app credential, which we prove by logging in as the app.
              if psql -v ON_ERROR_STOP=1 --set=app_pw="$APP_PASSWORD" <<'SQL'
              ALTER ROLE "<app>" WITH LOGIN NOCREATEDB NOCREATEROLE CONNECTION LIMIT 20 PASSWORD :'app_pw';
              SQL
              then
                echo "role <app> converged via ALTER"
              else
                echo "ALTER refused; verifying <app> already matches the app credential"
                if PGPASSWORD="$APP_PASSWORD" psql -h "$PGHOST" -U <app> -d postgres -c 'SELECT 1' >/dev/null 2>&1; then
                  echo "role <app> already provisioned by a prior authority; accepting"
                else
                  echo "FATAL: cannot manage role <app> and it does not match the app credential" >&2
                  exit 1
                fi
              fi

              # PG16+: creating a role grants the creator ADMIN but NOT SET, and
              # CREATE DATABASE ... OWNER requires the current role to SET ROLE to the
              # owner. As the role's creator we hold ADMIN, so grant ourselves SET
              # (idempotent). Without this a FIRST database creation fails with "must
              # be able to SET ROLE"; an app whose database predates this avoids it
              # only because the CREATE DATABASE below is then skipped.
              psql -v ON_ERROR_STOP=1 <<'SQL'
              GRANT "<app>" TO CURRENT_USER WITH SET TRUE;
              SQL

              # 2) Database: create <app> owned by <app> only if absent. CREATE
              #    DATABASE cannot run in a transaction/DO block, so drive it with the
              #    psql \gexec trick (run the SELECTed command only when it is emitted).
              psql -v ON_ERROR_STOP=1 <<'SQL'
              SELECT 'CREATE DATABASE "<app>" OWNER "<app>"'
              WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '<app>')\gexec
              SQL

              # 3) Lockdown: deny PUBLIC any way in. Run AS the app role (the database
              #    owner) using the mounted app password: the provisioner is deliberately
              #    barred from the app's database (it has no CONNECT), while the owner can
              #    always connect and revoke. Idempotent REVOKEs; re-runs are no-ops
              #    (INT-FOUNDRY-017).
              PGPASSWORD="$APP_PASSWORD" psql -v ON_ERROR_STOP=1 -h "$PGHOST" -U <app> -d <app> <<'SQL'
              REVOKE CONNECT, TEMPORARY ON DATABASE "<app>" FROM PUBLIC;
              REVOKE ALL ON SCHEMA public FROM PUBLIC;
              SQL

              echo "provisioned <app> database, role, and lockdown."
          env:
            - name: PGHOST
              value: shared-rw.databases.svc.cluster.local
            - name: PGPORT
              value: "5432"
            - name: PGDATABASE
              value: postgres
            - name: PGUSER
              valueFrom:
                secretKeyRef:
                  name: pg-db-provisioner
                  key: username
            - name: PGPASSWORD
              valueFrom:
                secretKeyRef:
                  name: pg-db-provisioner
                  key: password
          # The app password lives in the app-owned Secret <app>/pg-app-<app>, which
          # auto-reflects into this namespace as databases/pg-app-<app>. Mounted as a
          # file and read at runtime in the wait loop, so reflector lag is waited out
          # rather than baked into the pod env at start.
          volumeMounts:
            - name: app-cred
              mountPath: /var/run/app-cred
              readOnly: true
      volumes:
        - name: app-cred
          secret:
            secretName: pg-app-<app>
            optional: true"""


def render_database_job(app: str) -> str:
    """The provisioning Job for ``app``, rendered from the canonical template.

    Every ``<app>`` placeholder becomes ``app``. The result is validated
    isolation-clean (a per-app credential name and the SET-role self-grant) so a
    regression in the template fails closed here rather than shipping a manifest the
    isolation gate would reject downstream.
    """
    job = _PROVISION_JOB_TEMPLATE.replace(APP_PLACEHOLDER, app)
    if APP_PLACEHOLDER in job or not database_job_is_isolation_clean(job_text=job, app=app):
        raise ValueError(
            "the canonical database provisioning template did not render "
            f"isolation-clean for {app!r}; the template is broken"
        )
    return job
