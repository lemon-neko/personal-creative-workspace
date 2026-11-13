from app.career import CareerProfile
from app.career.domain.profile import CareerProfile as Profile, normalize_profile_fields


def test_profile_normalizes_only_known_facts_and_preserves_legacy_model():
    assert Profile is CareerProfile
    cleaned = normalize_profile_fields(
        {"facts": "  synthetic evidence  ", "unexpected": "discard"}
    )
    assert cleaned["facts"] == "synthetic evidence"
    assert cleaned["experience"] == ""
    assert "unexpected" not in cleaned
