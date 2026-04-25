from __future__ import annotations

from backend.memory.user_facts.rendering import render_living_profile_block


def test_biography_block_rendered():
    profile = {
        "biography": {
            "overview": "founder fundraising at acme; close ties to sarah.",
            "work": {"employer": "Acme", "role": "founder"},
            "relationships": [
                {"name": "Sarah", "kind": "colleague", "frequency": "weekly"},
                {"name": "Mom", "kind": "family", "frequency": "weekly"},
            ],
            "interests": ["VC", "design tooling"],
        },
    }
    out = render_living_profile_block(profile)
    assert "BIOGRAPHY" in out
    assert "founder fundraising" in out
    assert "Acme" in out
    assert "Sarah" in out


def test_biography_omitted_when_missing():
    out = render_living_profile_block({"summary": "hi"})
    assert "BIOGRAPHY" not in out
