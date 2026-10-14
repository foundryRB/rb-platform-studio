"""Documentation vocabulary follows the public application contracts."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from studio.domain.model.delivery_stage import DeliveryStage
from studio.domain.model.link_status import LinkStatus

ROOT = Path(__file__).resolve().parents[3]
DOCS = ROOT / "docs/src/content/docs"


def test_architecture_introduces_every_outbound_port() -> None:
    """REF-Documentation 7.10: the topology follows the port declarations."""
    page = (DOCS / "reference/architecture.md").read_text(encoding="utf-8")
    ports = ROOT / "studio-backend/studio/application/ports/outbound"
    for source in ports.glob("*.py"):
        for node in ast.parse(source.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.ClassDef):
                assert node.name in page, f"Architecture omits {node.name}"


def test_status_reference_names_the_contract_states() -> None:
    """REF-Documentation 7.10: the lookup vocabulary follows the public enums."""
    page = (DOCS / "reference/app-status.md").read_text(encoding="utf-8")
    for value in (*DeliveryStage, *LinkStatus):
        assert re.search(rf"\b{value.value}\b", page), f"Status reference omits {value.value}"
