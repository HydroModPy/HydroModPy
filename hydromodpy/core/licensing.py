"""The SPDX token this repository writes when nobody declared a licence.

It has one home because it is one fact. A run stamps it into its Zarr
attributes and its Parquet footers, and a job stamps it onto every input
resource whose licence no source registry could state; two constants would
eventually disagree, and the disagreement would be a legal claim about somebody
else's data.

Saying "undetermined" is the point. Telling a reader they may reuse under a
licence nobody granted is worse than telling them it is unknown, and the three
places that shipped a ``"CC-BY-4.0"`` literal are the reason this is written
down rather than defaulted.
"""

from __future__ import annotations

UNDETERMINED_LICENSE = "LicenseRef-undetermined"
"""SPDX identifier for a licence that was never declared."""


__all__ = ["UNDETERMINED_LICENSE"]
