"""Who a request acts for, and which storage scope owns their artifacts.

The local deployment profile resolves a constant principal, so a single
operator sees no accounts and no sign-in. The hosted profile resolves the
authenticated subject instead. Product code never asks which profile it is
running under: it reads a workspace off the principal and scopes storage by
it, so the isolation rule is the same in both profiles (ADR 0016).
"""

from __future__ import annotations

from dataclasses import dataclass


class InvalidWorkspace(ValueError):
    """A workspace key that cannot be used as a single storage segment."""


_RESERVED_SEGMENTS = frozenset({"", ".", ".."})
_SEPARATORS = ("/", "\\", "\x00")


@dataclass(frozen=True)
class Principal:
    """The owner of a review session and everything derived from it.

    ``workspace`` is the scoping key for artifact storage and, later, catalog
    rows. It is validated as a single safe path segment because it is
    concatenated onto the artifact root: a principal carrying ``..`` or a
    separator would otherwise escape its own scope and read another
    workspace's artifacts.
    """

    user_id: str
    workspace: str

    def __post_init__(self) -> None:
        if self.workspace in _RESERVED_SEGMENTS:
            raise InvalidWorkspace(
                f"workspace must be a usable storage segment, got {self.workspace!r}"
            )
        if self.workspace.strip() != self.workspace:
            raise InvalidWorkspace(
                f"workspace must not be padded with whitespace, got {self.workspace!r}"
            )
        for separator in _SEPARATORS:
            if separator in self.workspace:
                raise InvalidWorkspace(
                    f"workspace must be a single path segment, got {self.workspace!r}"
                )
        if self.user_id == "":
            raise InvalidWorkspace("user_id must not be empty")


LOCAL_PRINCIPAL = Principal(user_id="local", workspace="local")
"""The single operator of a local-profile deployment."""


def resolve_local_principal() -> Principal:
    """Resolve the principal for the local deployment profile.

    Always the same operator: the local profile has no accounts, so this is a
    constant rather than a lookup.
    """

    return LOCAL_PRINCIPAL
