"""The branch names every gated change rides, named once.

Each act the studio gates prepares its own branch off the install's deploy
branch, and the recovery verb has to recognise one when an operator hands it
back. Both sides read these helpers, so a branch the gate can create is always
a branch the cancel verb can identify.
"""

from __future__ import annotations

import re

__all__ = [
    "CHANGE_BRANCH_PREFIXES",
    "database_branch",
    "identity_branch",
    "events_branch",
    "is_change_branch",
    "offboard_branch",
    "onboard_branch",
    "reconcile_branch",
    "reconcile_identity_branch",
    "setting_branch",
]

CHANGE_BRANCH_PREFIXES: tuple[str, ...] = (
    "onboard/",
    "offboard/",
    "reconcile/",
    "settings/",
)

# One flat segment of the characters an app name or a settings key renders to.
# Slashes and dot-dot stay out so no name can climb out of its prefix.
_TARGET = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def onboard_branch(app: str) -> str:
    return f"onboard/{app}"


def database_branch(app: str) -> str:
    return f"onboard/{app}-db"


def identity_branch(app: str) -> str:
    return f"onboard/{app}-identity"


def events_branch(app: str) -> str:
    return f"onboard/{app}-events"


def offboard_branch(app: str) -> str:
    return f"offboard/{app}"


def reconcile_branch(app: str) -> str:
    return f"reconcile/{app}"


def reconcile_identity_branch(app: str) -> str:
    return f"reconcile/{app}-identity"


def setting_branch(key: str) -> str:
    return f"settings/{key.replace('.', '-')}"


def is_change_branch(branch: str) -> bool:
    """Whether `branch` is one the studio's gate prepares.

    The guard on every branch deletion: the studio may discard what it created
    and nothing else, so the install's deploy branch and the platform repo's
    main are unreachable from any verb that deletes.
    """
    prefix = next((p for p in CHANGE_BRANCH_PREFIXES if branch.startswith(p)), None)
    if prefix is None:
        return False
    target = branch[len(prefix) :]
    return bool(_TARGET.match(target)) and ".." not in target
