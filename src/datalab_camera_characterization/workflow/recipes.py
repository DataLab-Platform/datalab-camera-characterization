"""Camera recipe registry.

Recipes are added here as headless workflows become available. The empty
registry keeps host adapters honest during the architecture-only phase.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datalab.recipes import RecipeDescriptor

CAMERA_RECIPES: tuple[RecipeDescriptor, ...] = ()

__all__ = ["CAMERA_RECIPES"]
