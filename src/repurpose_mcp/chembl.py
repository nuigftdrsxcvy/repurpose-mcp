"""ChEMBL web services: first-approval year and withdrawn flag (no longer exposed by Open Targets)."""

from __future__ import annotations

from typing import Any

from repurpose_mcp.http import ApiClient

MOLECULE_URL = "https://www.ebi.ac.uk/chembl/api/data/molecule.json"
_CHUNK = 50


async def molecules(client: ApiClient, chembl_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Map ChEMBL id -> {"first_approval": int | None, "withdrawn_flag": bool | None}."""
    ids = sorted(set(chembl_ids))
    out: dict[str, dict[str, Any]] = {}
    for i in range(0, len(ids), _CHUNK):
        chunk = ids[i : i + _CHUNK]
        data = await client.get_json(
            MOLECULE_URL,
            {
                "molecule_chembl_id__in": ",".join(chunk),
                "only": "molecule_chembl_id,first_approval,withdrawn_flag",
                "limit": len(chunk),
            },
        )
        for m in data.get("molecules", []):
            out[m["molecule_chembl_id"]] = {
                "first_approval": m.get("first_approval"),
                "withdrawn_flag": m.get("withdrawn_flag"),
            }
    return out
