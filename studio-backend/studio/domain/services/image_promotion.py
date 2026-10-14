"""ArgoCD Image Updater bindings: one alias per released image.

Promotion is only as real as both legs of each binding: the image-list alias
must watch a GHCR package the app's CI actually publishes, and the alias's
helm values paths must be ones the app's chart actually reads off the deploy
branch's prod values (the write-back target). A broken binding has no crash
and no red status - Image Updater simply finds nothing to do - so the app
pins its first tag forever while CI keeps releasing (alexandria shipped
alexandria-server/-client/-docs with tags at alexandria.images.<comp>.tag
while a single alias watched the unreleased package alexandria and wrote
alexandria.image.tag; nothing ever promoted).

The render side emits the canonical binding shape for the component list an
onboarding declares. The validation side holds every Application to that same
shape - the install carries one binding layout, rendered and gated by the
same system - and then, when the deploy values are readable, checks the
bindings against those values in both directions. The app repo's compose
file is the manifest of what CI actually publishes, so a third leg, when
that repo is readable, holds the alias set to the released set itself: the
compose ``build:`` services plus the docs image.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

__all__ = [
    "ANNOTATION_PREFIX",
    "FROZEN_TAG_FILTER",
    "PROMOTION_AUTO",
    "PROMOTION_MANUAL",
    "PROMOTION_UNBOUND",
    "bound_tag_values",
    "frozen_aliases",
    "image_list_aliases",
    "image_updater_aliases",
    "image_updater_annotation_lines",
    "image_updater_problems",
    "invalid_image_components",
    "promotion_mode",
    "released_packages",
    "released_set_problems",
    "unpromoted_bindings",
]

ANNOTATION_PREFIX = "argocd-image-updater.argoproj.io/"

# The tag filter a frozen alias carries. Image Updater's ignore-tags takes a
# comma-separated list of glob patterns, so "*" ignores every tag: the alias
# keeps its whole binding and simply never finds a candidate to promote. That
# is what makes freezing gate-compatible - the image-list, the helm paths and
# the released set all stay intact, so every promotion conformance row keeps
# running and the status read keeps reporting the pinned tag, which dropping
# the annotations would take dark.
#
# The value is also the freeze SENTINEL: an ignore-tags carrying anything else
# is a real filter an operator wrote, and the toggle neither reads it as frozen
# nor removes it. It is quoted in YAML because a bare * opens an alias node.
FROZEN_TAG_FILTER = "*"

# How an Application promotes, as the team manifest reports it.
PROMOTION_AUTO = "auto"  # at least one alias still promotes
PROMOTION_MANUAL = "manual"  # every declared alias is frozen
PROMOTION_UNBOUND = "none"  # no image-list: nothing promotes, nothing to freeze

_GHCR = "ghcr.io"

# A component name rides into a GHCR package name (<app>-<comp>) and a helm
# values key (<app>.images.<comp>), so it takes the same lowercase-label shape
# as an app name.
_COMPONENT_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")

_IMAGE_LIST_ENTRY = re.compile(r"^(?P<alias>[a-z0-9][a-z0-9-]*)=(?P<image>\S+)$")

# The alias-scoped annotation forms Image Updater reads: anything of this
# shape names an alias, and an alias outside image-list binds nothing.
_ALIAS_SCOPED = re.compile(
    r"^(?P<alias>[a-z0-9][a-z0-9-]*)\."
    r"(?:update-strategy|helm\..+|kustomize\..+|force-update|allow-tags|ignore-tags"
    r"|pull-secret|platforms)$"
)


def invalid_image_components(components: tuple[str, ...]) -> tuple[str, ...]:
    """The component names unusable as image bindings: not a lowercase label
    (letters, digits, hyphens; starts and ends alphanumeric), or duplicated.

    A LONE ``app`` component is also refused: ``app`` is the alias of the
    single-image shape (declared as no components at all), so a one-entry
    ``["app"]`` list would render the multi-image binding ``<app>-app`` /
    ``<app>.images.app.*`` while the shape check reads a sole ``app`` alias
    as the single-image form - the one input where render and check disagree.
    ``app`` among several components is fine (the check reads that as multi).
    """
    if components == ("app",):
        return ("app",)
    seen: set[str] = set()
    bad: list[str] = []
    for component in components:
        if not _COMPONENT_LABEL.match(component) or component in seen:
            bad.append(component)
        seen.add(component)
    return tuple(bad)


def _bindings(app: str, components: tuple[str, ...]) -> tuple[tuple[str, str, str], ...]:
    """(alias, package, values-stem) per released image, in the canonical shape.

    No components: the app releases the one package ``<app>`` and its chart
    reads ``<app>.image.{repository,tag}`` (alias ``app``). With components:
    one alias per component; CI publishes ``<app>-<component>`` and the chart
    reads ``<app>.images.<component>.{repository,tag}``.
    """
    if not components:
        return (("app", app, f"{app}.image"),)
    return tuple(
        (component, f"{app}-{component}", f"{app}.images.{component}")
        for component in components
    )


def image_updater_annotation_lines(
    *, app: str, registry: str, components: tuple[str, ...]
) -> str:
    """The Image Updater annotation lines of an app's Application manifest,
    indented for the metadata.annotations block: the image-list plus, per
    alias, the semver update strategy and the helm image-name/-tag paths.
    ``registry`` is the install's ``<host>/<owner>`` prefix (ADR-044, #164)."""
    bindings = _bindings(app, components)
    image_list = ",".join(
        f"{alias}={registry}/{package}" for alias, package, _ in bindings
    )
    lines = [f"{ANNOTATION_PREFIX}image-list: {image_list}"]
    for alias, _, stem in bindings:
        lines.append(f"{ANNOTATION_PREFIX}{alias}.update-strategy: semver")
        lines.append(f"{ANNOTATION_PREFIX}{alias}.helm.image-name: {stem}.repository")
        lines.append(f"{ANNOTATION_PREFIX}{alias}.helm.image-tag: {stem}.tag")
    return "\n".join(f"    {line}" for line in lines)


def image_list_aliases(image_list: str) -> tuple[str, ...]:
    """The aliases one image-list VALUE declares (malformed entries skipped).

    Split out from ``image_updater_aliases`` so a caller holding the raw
    annotation line (the freeze toggle, which edits the manifest text rather
    than a parsed mapping) reads the alias set through the same parse.
    """
    aliases: list[str] = []
    for entry in image_list.split(","):
        match = _IMAGE_LIST_ENTRY.match(entry.strip())
        if match:
            aliases.append(match.group("alias"))
    return tuple(aliases)


def image_updater_aliases(annotations: Mapping[str, str]) -> tuple[str, ...]:
    """The aliases the image-list annotation declares (malformed entries skipped)."""
    return image_list_aliases(str(annotations.get(f"{ANNOTATION_PREFIX}image-list", "")))


def frozen_aliases(annotations: Mapping[str, str]) -> tuple[str, ...]:
    """The declared aliases whose tag filter is the freeze sentinel.

    An alias-scoped ``ignore-tags`` of exactly ``*`` is the toggle's own mark:
    the alias considers no tag, so nothing promotes through it. Any other
    ignore-tags value is an operator's real filter and is not a freeze.
    """
    return tuple(
        alias
        for alias in image_updater_aliases(annotations)
        if str(annotations.get(f"{ANNOTATION_PREFIX}{alias}.ignore-tags", "")).strip()
        == FROZEN_TAG_FILTER
    )


def promotion_mode(annotations: Mapping[str, str]) -> str:
    """How this Application promotes: auto, manual (frozen), or none.

    ``none`` is an Application declaring no image-list at all - nothing watches
    its images, so there is no promotion to freeze or resume. A PARTIAL freeze
    (some aliases frozen, only reachable by a hand edit) reads as ``auto``,
    which is the honest answer: something still promotes. Freezing such an app
    fills in the aliases the hand edit missed.
    """
    aliases = set(image_updater_aliases(annotations))
    if not aliases:
        return PROMOTION_UNBOUND
    return PROMOTION_MANUAL if set(frozen_aliases(annotations)) == aliases else PROMOTION_AUTO


def image_updater_problems(
    *, app: str, repo_owner: str, annotations: Mapping[str, str], registry: str = ""
) -> tuple[str, ...]:
    """Deviations of an Application's Image Updater annotations from the
    canonical binding shape the skeleton renders.

    The install carries one binding shape, so every Application is held to
    it: a single released image is the alias ``app`` watching the package
    ``<app>`` and writing ``<app>.image.{repository,tag}``; several released
    images are one alias per component, each watching ``<app>-<component>``
    and writing ``<app>.images.<component>.{repository,tag}``. The image-list
    must parse with unique aliases, every watched package must sit under the
    install's registry (its declared ``registry`` prefix when given, else GHCR
    under the app repo's owner - the pre-block shape), and no alias-scoped
    annotation may float free of the image-list. Whether the bound paths are
    the ones the deploy values actually carry is ``unpromoted_bindings``' half.
    """
    problems: list[str] = []
    aliases: list[str] = []
    images: dict[str, str] = {}
    for entry in str(annotations[f"{ANNOTATION_PREFIX}image-list"]).split(","):
        match = _IMAGE_LIST_ENTRY.match(entry.strip())
        if not match:
            problems.append(f"image-list entry {entry.strip()!r} is not alias=image")
            continue
        alias, image = match.group("alias"), match.group("image")
        if alias in aliases:
            problems.append(f"alias {alias!r} appears twice in image-list")
        aliases.append(alias)
        images[alias] = image
    single = aliases == ["app"]
    org = repo_owner.lower()
    for alias in aliases:
        package = app if single else f"{app}-{alias}"
        stem = f"{app}.image" if single else f"{app}.images.{alias}"
        if registry:
            expected_image = f"{registry}/{package}"
        else:
            expected_image = f"{_GHCR}/{org}/{package}" if org else ""
        if not expected_image or images[alias] != expected_image:
            problems.append(
                f"alias {alias!r} watches {images[alias]}: the canonical binding "
                f"watches {expected_image or '<owner underivable from repoURL>'}"
            )
        name_path = annotations.get(f"{ANNOTATION_PREFIX}{alias}.helm.image-name")
        tag_path = annotations.get(f"{ANNOTATION_PREFIX}{alias}.helm.image-tag")
        if not name_path or not tag_path:
            problems.append(
                f"alias {alias!r} has no helm.image-name/-tag binding, "
                "so its updates write nowhere"
            )
            continue
        if name_path != f"{stem}.repository" or tag_path != f"{stem}.tag":
            problems.append(
                f"alias {alias!r} binds {name_path} / {tag_path}: the canonical "
                f"binding writes {stem}.repository / {stem}.tag"
            )
    for key in annotations:
        if not key.startswith(ANNOTATION_PREFIX):
            continue
        match = _ALIAS_SCOPED.match(key.removeprefix(ANNOTATION_PREFIX))
        if match and match.group("alias") not in aliases:
            problems.append(
                f"annotation {key} binds alias {match.group('alias')!r}, "
                "which image-list does not declare"
            )
    return tuple(sorted(problems))


def unpromoted_bindings(
    *, app: str, annotations: Mapping[str, str], deploy_values: Mapping[str, object]
) -> tuple[str, ...]:
    """Mismatches between the bindings and the deploy values they write.

    Forward: every alias's helm.image-tag path must resolve inside the deploy
    values - CI seeds exactly the paths the chart reads there, so a path the
    values do not carry is one the chart does not read, and the write moves
    nothing the release uses. Reverse: every image tag the deploy values
    carry (a ``tag`` leaf under an ``image``/``images`` mapping at the app's
    root) must be written by some alias - a released image with no alias
    watching it never promotes at all.

    This reverse leg is the fleet's docs-binding invariant: every app ships a
    docs site as its own promoted ``<app>-docs`` image, so its chart reads a
    ``<app>.images.docs.tag`` the deploy values carry, and this leg then fails
    any app that does not bind a ``docs`` alias to write it. No separate
    serves-docs check is needed - the values-carried tag is the standing proof
    the docs image exists, and holding every such tag to a binding covers it.
    """
    problems: list[str] = []
    bound = {
        str(annotations.get(f"{ANNOTATION_PREFIX}{alias}.helm.image-tag", ""))
        for alias in image_updater_aliases(annotations)
    }
    bound.discard("")
    for tag_path in sorted(bound):
        if not _resolves(deploy_values, tag_path):
            problems.append(
                f"the bound tag path {tag_path} is not in the deploy values, "
                "so the chart does not read what promotion writes"
            )
    for tag_path in _image_tag_paths(deploy_values, root=app):
        if tag_path not in bound:
            problems.append(
                f"the deploy values carry {tag_path} but no alias writes it, "
                "so that image never promotes"
            )
    return tuple(sorted(problems))


def released_packages(
    *, app: str, compose: Mapping[str, object], docs_image: bool
) -> tuple[str, ...]:
    """The GHCR package names the app repo's CI actually publishes.

    ``devops/docker-compose.yml`` is the repo's single source of truth for
    the images it ships: CI builds and pushes every service carrying a
    ``build:`` section, named by its ``image:`` basename with the tag
    stripped (the service name when no ``image:`` is set, CI's own
    fallback). The docs site is published beside them as ``<app>-docs``
    whenever ``docs/Dockerfile`` exists.
    """
    packages: set[str] = set()
    services = compose.get("services")
    if isinstance(services, Mapping):
        for name, service in services.items():
            if not isinstance(service, Mapping) or not service.get("build"):
                continue
            image = str(service.get("image") or name)
            packages.add(image.split("/")[-1].split(":")[0].lower())
    if docs_image:
        packages.add(f"{app}-docs")
    return tuple(sorted(packages))


def released_set_problems(
    *, annotations: Mapping[str, str], released: tuple[str, ...]
) -> tuple[str, ...]:
    """Mismatches between the image-list and the released set.

    Forward: every alias must watch a released package - a phantom alias
    (watching a package CI never publishes) is a binding that promotes
    nothing. Reverse: every released package must be watched by some alias -
    a released image no alias watches never promotes at all. Both are silent
    (no crash, no red status, and the values-bound legs can agree with a
    phantom binding when the deploy values carry its path), so the set
    mismatch fails here instead.
    """
    problems: list[str] = []
    watched: dict[str, str] = {}
    for entry in str(annotations.get(f"{ANNOTATION_PREFIX}image-list", "")).split(","):
        match = _IMAGE_LIST_ENTRY.match(entry.strip())
        if match:
            image = match.group("image")
            watched[match.group("alias")] = image.split("/")[-1].split(":")[0].lower()
    for alias, package in sorted(watched.items()):
        if package not in released:
            problems.append(
                f"alias {alias!r} watches {package}, which the app repo does not "
                "release (no compose build: service publishes it and it is not "
                "the docs image), so it promotes nothing"
            )
    for package in released:
        if package not in watched.values():
            problems.append(
                f"the app repo releases {package} but no alias watches it, "
                "so that image never promotes"
            )
    return tuple(sorted(problems))


def bound_tag_values(
    *, annotations: Mapping[str, str], deploy_values: Mapping[str, object]
) -> tuple[tuple[str, object | None], ...]:
    """Each alias's bound helm.image-tag path with the value the deploy
    values currently carry at it (None when the path does not resolve).

    The read side of the binding: ``unpromoted_bindings`` judges the paths,
    this reports what promotion has actually written, so a status read can
    show the tag each image currently pins.
    """
    bound: list[tuple[str, object | None]] = []
    for alias in image_updater_aliases(annotations):
        tag_path = str(annotations.get(f"{ANNOTATION_PREFIX}{alias}.helm.image-tag", ""))
        if tag_path:
            bound.append((tag_path, _value_at(deploy_values, tag_path)))
    return tuple(sorted(bound))


def _value_at(values: Mapping[str, object], dotted_path: str) -> object | None:
    node: object = values
    for segment in dotted_path.split("."):
        if not isinstance(node, Mapping) or segment not in node:
            return None
        node = node[segment]
    return node


def _resolves(values: Mapping[str, object], dotted_path: str) -> bool:
    node: object = values
    for segment in dotted_path.split("."):
        if not isinstance(node, Mapping) or segment not in node:
            return False
        node = node[segment]
    return True


def _image_tag_paths(values: Mapping[str, object], *, root: str) -> tuple[str, ...]:
    """Every dotted path under ``root`` ending in a ``tag`` leaf that sits
    below an ``image``/``images`` segment: the tags CI seeded for promotion."""
    found: list[str] = []

    def walk(node: object, path: tuple[str, ...]) -> None:
        if not isinstance(node, Mapping):
            if path and path[-1] == "tag" and {"image", "images"} & set(path[:-1]):
                found.append(".".join(path))
            return
        for key, child in node.items():
            walk(child, (*path, str(key)))

    walk(values.get(root), (root,))
    return tuple(sorted(found))
