"""i18n tests (F10.1)."""
from __future__ import annotations

import json
from pathlib import Path

from app import i18n

TRANSLATIONS_DIR = Path(__file__).resolve().parents[1] / "app" / "translations"


def test_en_and_bn_have_identical_keys():
    en = json.loads((TRANSLATIONS_DIR / "en.json").read_text(encoding="utf-8"))
    bn = json.loads((TRANSLATIONS_DIR / "bn.json").read_text(encoding="utf-8"))
    assert set(en.keys()) == set(bn.keys())
    assert en  # not empty


def test_unknown_lang_falls_back_to_english():
    assert i18n.t("app.name", lang="xx") == i18n.t("app.name", lang="en")


def test_known_keys_translate():
    en = json.loads((TRANSLATIONS_DIR / "en.json").read_text(encoding="utf-8"))
    bn = json.loads((TRANSLATIONS_DIR / "bn.json").read_text(encoding="utf-8"))
    assert en["app.name"] == "BloodLink"
    assert "app.name" in bn
    assert bn["app.name"] != en["app.name"]  # at least one real translation
