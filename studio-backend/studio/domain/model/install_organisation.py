"""Where an install's repositories live, as its deploy branch declares them (ADR-044)."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["InstallOrganisation"]


@dataclass(frozen=True)
class InstallOrganisation:
    """`github_org` is the organisation's login (the path segment of
    githubOrgUrl); `platform_repo` and `ci_repo` are repository names under
    it. Each is empty when the branch does not declare it."""

    github_org: str = ""
    platform_repo: str = ""
    ci_repo: str = ""

    @property
    def declared(self) -> bool:
        return bool(self.github_org)

    def org_or(self, default: str) -> str:
        """The declared organisation, or ``default`` for a pre-block branch."""
        return self.github_org or default

    def platform_repo_or(self, default: str = "foundry-platform") -> str:
        return self.platform_repo or default

    def ci_repo_or(self, default: str = "ci") -> str:
        return self.ci_repo or default

    @staticmethod
    def from_values(raw: dict) -> InstallOrganisation:
        """Read the fact off a parsed values.yaml; missing keys stay empty."""
        url = str(raw.get("githubOrgUrl") or "").strip().rstrip("/")
        org = url.rsplit("/", 1)[-1] if url else ""
        return InstallOrganisation(
            github_org=org,
            platform_repo=str(raw.get("platformRepo") or "").strip(),
            ci_repo=str(raw.get("ciRepo") or "").strip(),
        )
