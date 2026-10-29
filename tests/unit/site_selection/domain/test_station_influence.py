import pytest

from hydromodpy.spatial.site_selection.domain.station_influence import (
    station_influence_diagnostics,
    station_influence_metadata_from_hubeau,
)

pytestmark = pytest.mark.fast


@pytest.mark.parametrize(("attributes", "status", "flags"), [
    ({"influence_generale_site": True}, "general_influence", ["general_influence"]),
    ({"general_influence": False}, "no_known_influence", []),
    ({"influence_generale_site": "Influencée"}, "general_influence", ["general_influence"]),
    ({"influence_generale_site": "2,5"}, "general_influence", ["general_influence"]),
    ({"influence_generale_site": "Sans influence notable"}, "no_known_influence", []),
    ({"influence_generale_site": "faible influence aval"}, "general_influence", ["general_influence"]),
    ({"influence_generale_site": "Non renseigné"}, "unknown", []),
    ({"influence_generale_site": "peut-être"}, "unknown", []),
    ({"influence_locale_station": "oui"}, "local_influence", ["local_influence"]),
    ({"commentaire_influence_locale_station": "Écluse et canal", "commentaire_station": " "},
     "unknown", ["local_influence_comment_keyword"]),
    ({"commentaire_influence_generale_site": "Barrage, barrage"}, "unknown", ["general_influence_comment_keyword"]),
])  # fmt: skip
def test_influence_metadata_reads_as_one_status(attributes, status, flags):
    diagnostics = station_influence_diagnostics(attributes)
    assert diagnostics.status == status
    assert diagnostics.flags == flags
    assert diagnostics.has_raw_evidence


def test_a_comment_matches_the_keywords_once_without_accents():
    diagnostics = station_influence_diagnostics(
        {"commentaire_station": "Barrage. Barrage en amont, écluse."},
        comment_keywords=["barrage", "Écluse", "", "BARRAGE"],
    )
    assert diagnostics.matched_keywords == ["barrage", "ecluse"]


def test_only_the_filled_hubeau_influence_fields_are_kept():
    info = {"influence_generale_site": "1", "commentaire_station": "", "libelle_site": "X"}
    assert station_influence_metadata_from_hubeau(info) == {"influence_generale_site": "1"}
