"""INT-GRANT-001: the database provisioning Job is rendered from the studio's own
canonical template, fully tokenized and validated isolation-clean -- not mirrored
from a live reference app whose bugs a rename would carry (sabbito-bazarrito#7)."""

from __future__ import annotations

import pytest
from pytest_intent import intent

import studio.domain.services.database_grant as grant_mod
from studio.domain.services.database_grant import APP_PLACEHOLDER, render_database_job
from studio.domain.services.team_documents import database_job_is_isolation_clean


@intent("INT-GRANT-001")
@pytest.mark.parametrize("app", ["scrapyard", "sabbito-bazarrito", "alpha-app"])
def test_rendered_job_is_isolation_clean_for_any_app(app: str) -> None:
    job = render_database_job(app)
    # Fully substituted: no placeholder token survives (a dashed name stays quoted).
    assert APP_PLACEHOLDER not in job
    # The named app owns the Job everywhere it matters.
    assert f"name: pg-{app}-provision" in job
    assert f'CREATE DATABASE "{app}" OWNER "{app}"' in job
    # The two isolation fixes, guaranteed by construction (sabbito-bazarrito#7):
    assert f"secretName: pg-app-{app}" in job  # per-app credential name...
    assert "secretName: pg-app\n" not in job  # ...never the shared bare pg-app
    assert f'GRANT "{app}" TO CURRENT_USER WITH SET TRUE' in job  # PG16 SET-role grant
    assert database_job_is_isolation_clean(job_text=job, app=app)


def test_render_fails_closed_if_the_template_regresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Were the template ever edited back to the shared bare name, rendering raises
    rather than shipping a manifest the isolation gate (INT-FOUNDRY-040) would reject."""
    broken = grant_mod._PROVISION_JOB_TEMPLATE.replace("pg-app-<app>", "pg-app")
    monkeypatch.setattr(grant_mod, "_PROVISION_JOB_TEMPLATE", broken)
    with pytest.raises(ValueError, match="isolation-clean"):
        render_database_job("scrapyard")
