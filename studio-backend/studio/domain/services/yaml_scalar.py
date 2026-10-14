"""Render a caller-supplied string as a YAML scalar that reads back whole.

Every value the studio writes into YAML that it did not itself author - an
app's display name, its description, its icon - is free text, and free text
carries the characters YAML reads structurally: a colon-space opens a mapping,
a quote or a backslash breaks a quoted scalar's escaping, an exotic line
separator ends the scalar early. Interpolated raw, such a value does not come
back as the string that went in; it comes back as a different document, or as
a parse error. A description reading "A companion for X: roster and routes" is
ordinary English and enough to do it.

Two shapes over the one guarantee. ``yaml_quoted`` always double-quotes, for a
field whose value is free text by definition. ``yaml_scalar`` leaves an
unambiguous value plain and quotes only what needs it, for fields whose values
are ordinarily short, plain, and read by hand in the rendered file.

The double-quoted form is a JSON string literal: JSON's escapes are a subset
of YAML's double-quoted escapes, so every YAML parser reads a JSON literal
back as the string it encodes.
"""

from __future__ import annotations

import json
import re

__all__ = ["yaml_quoted", "yaml_scalar"]

# Characters YAML gives no structural meaning, opening on one that starts no
# indicator: the shape a plain scalar may take.
_PLAIN_SCALAR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/-]*$")

# Plain forms YAML resolves to something other than the string written: the
# booleans of YAML 1.1 (go-yaml, which Helm and ArgoCD read with, takes the
# single-letter ones too) and any bare number.
_NOT_A_STRING = re.compile(r"^(?:y|n|yes|no|true|false|on|off|\d+(?:\.\d*)?)$", re.IGNORECASE)

# YAML breaks a line on NEL, LINE SEPARATOR, and PARAGRAPH SEPARATOR; JSON
# holds them as ordinary characters and leaves them literal inside the quotes.
_YAML_LINE_BREAKS = {0x85: "\\u0085", 0x2028: "\\u2028", 0x2029: "\\u2029"}


def yaml_quoted(value: str) -> str:
    """``value`` as a double-quoted YAML scalar, every escape in place."""
    return json.dumps(value, ensure_ascii=False).translate(_YAML_LINE_BREAKS)


def yaml_scalar(value: str) -> str:
    """``value`` plain where YAML reads it back unchanged, double-quoted otherwise."""
    if _PLAIN_SCALAR.match(value) and not _NOT_A_STRING.match(value):
        return value
    return yaml_quoted(value)
