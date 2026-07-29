"""Reference resolver: map friendly names to the GUIDs/URLs Purview requires.

Reads catalog/catalog.json and resolves sensitive-info-type names, group names, and
SharePoint site names. Fail-closed: an unresolved name raises rather than silently
producing a policy that matches nothing.
"""
import json
import os

DEFAULT_CATALOG = os.path.join(os.path.dirname(__file__), "..", "catalog", "catalog.json")


class ResolutionError(Exception):
    """Raised when a name cannot be resolved from the catalog."""


class Catalog:
    def __init__(self, data):
        self.sits = data.get("sensitiveInfoTypes", {})
        self.labels = data.get("sensitivityLabels", {})
        self.dictionaries = data.get("keywordDictionaries", {})
        self.classifiers = data.get("trainableClassifiers", {})
        self.groups = data.get("groups", {})
        self.sites = data.get("sites", {})
        self.custom = set(data.get("customSensitiveInfoTypes", []))

    def sit(self, name):
        """Return {'name', 'id'} for a sensitive info type, or raise."""
        if name not in self.sits:
            raise ResolutionError(
                f"Sensitive info type '{name}' is not in the catalog. "
                f"Refresh catalog.json (Update-Catalog.ps1) or fix the name."
            )
        return {"name": name, "id": self.sits[name]}

    def label(self, name):
        """Return {'name': GUID, 'type': 'Sensitivity'} for a sensitivity label, or raise."""
        if name not in self.labels:
            raise ResolutionError(
                f"Sensitivity label '{name}' is not in the catalog. Refresh catalog.json (Update-Catalog.ps1)."
            )
        return {"name": self.labels[name], "type": "Sensitivity"}

    def group(self, name):
        """Return the group's GUID (scoping params require the GUID, not the name)."""
        if name not in self.groups:
            raise ResolutionError(
                f"Group '{name}' is not in the catalog. Add it via Update-Catalog.ps1."
            )
        return self.groups[name]

    def site(self, name):
        """Return the SharePoint site URL for a site name, or raise."""
        if name not in self.sites:
            raise ResolutionError(
                f"SharePoint site '{name}' is not in the catalog. Add it via Update-Catalog.ps1."
            )
        return self.sites[name]


def load_catalog(path=None):
    path = path or DEFAULT_CATALOG
    # utf-8-sig tolerates a BOM (Windows PowerShell writes one) as well as plain UTF-8.
    with open(path, encoding="utf-8-sig") as f:
        return Catalog(json.load(f))
