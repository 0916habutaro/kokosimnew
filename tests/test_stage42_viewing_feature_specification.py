"""Stage42 viewing feature specification: static governance, no GUI implementation.

The inventory is an intentionally editable design document. These tests
enforce traceable source references and safe evidence labels, but do not
promote prototype UI or secondary research to production capabilities.
"""
from __future__ import annotations

import csv
import io
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CATALOG=ROOT/"docs/design/viewing_feature_catalog_stage42.csv"
MAIN=ROOT/"docs/design/viewing_features.md"
NAV=ROOT/"docs/design/viewing_screen_navigation.md"
DATA=ROOT/"docs/design/viewing_data_requirements.md"

FIELDS=(
    "feature_id","name_ja","category","current_state",
    "priority_draft","data_readiness","reference_path","scope_note",
)
STATES={
    "gui_prototype","read_model_only","preview_only",
    "design_only","future_candidate",
}
READINESS={"available","partial","needs_new_data","official_unverified"}
CATEGORIES={
    "home","date","tournament","match","school","player",
    "ranking","history","analytics","navigation",
    "provenance","export","ux",
}
KEY_FEATURES={
    "VIEW-DATE-001","VIEW-TOUR-003","VIEW-TOUR-004",
    "VIEW-MATCH-005","VIEW-SCHOOL-006","VIEW-SCHOOL-007",
    "VIEW-PLAYER-006","VIEW-RANK-001","VIEW-HISTORY-004",
    "VIEW-META-003","VIEW-UX-002",
}


def read_catalog(text: str|None=None) -> list[dict]:
    if text is None:
        text=CATALOG.read_text(encoding="utf-8")
    with io.StringIO(text,newline="") as stream:
        reader=csv.DictReader(stream)
        if tuple(reader.fieldnames or ())!=FIELDS:
            raise ValueError("feature catalog columns changed")
        return list(reader)


def audit_catalog(items: list[dict]) -> list[str]:
    errors=[]
    if len(items)<71:
        errors.append("Stage42 71 baseline viewing features were dropped")
    seen=set()
    for i,entry in enumerate(items,1):
        feature=entry["feature_id"]
        if (not feature.startswith("VIEW-") or feature in seen):
            errors.append(f"missing/duplicate feature ID: row {i}")
        seen.add(feature)
        if entry["category"] not in CATEGORIES:
            errors.append(f"unknown category: {feature}")
        if entry["current_state"] not in STATES:
            errors.append(f"invalid state: {feature}")
        if entry["priority_draft"] not in ("P0","P1","P2"):
            errors.append(f"invalid proposed priority: {feature}")
        if entry["data_readiness"] not in READINESS:
            errors.append(f"invalid data readiness: {feature}")
        if not entry["name_ja"].strip() or not entry["scope_note"].strip():
            errors.append(f"empty title or safety note: {feature}")
        source=ROOT/entry["reference_path"]
        if (source.suffix not in (".py",".md") or not source.is_file()
                or not source.resolve().is_relative_to(ROOT.resolve())):
            errors.append(f"unverifiable local reference: {feature}")
        if (entry["current_state"]=="preview_only"
                and entry["data_readiness"]=="available"):
            errors.append(f"preview claimed globally available: {feature}")
    if not KEY_FEATURES.issubset(seen):
        errors.append("baseline core features or caveats disappeared")
    if {x["category"] for x in items} != CATEGORIES:
        errors.append("all 13 viewing capability categories must be covered")
    return errors


class Stage42ViewingSpecificationTests(unittest.TestCase):
    def test_catalog_is_traceable_and_complete(self):
        rows=read_catalog()
        self.assertEqual(audit_catalog(rows),[])
        self.assertEqual(len(rows),71)
        self.assertEqual(len({x["feature_id"] for x in rows}),71)

    def test_initial_state_classification_is_not_overstated(self):
        rows=read_catalog()
        counts={status:sum(x["current_state"]==status for x in rows) for status in STATES}
        self.assertEqual(counts,{
            "gui_prototype":22,"read_model_only":10,
            "preview_only":6,"design_only":4,"future_candidate":29,
        })
        self.assertEqual(
            next(row for row in rows if row["feature_id"]=="VIEW-TOUR-004")["current_state"],
            "preview_only",
        )
        self.assertEqual(
            next(row for row in rows if row["feature_id"]=="VIEW-PLAYER-007")["current_state"],
            "future_candidate",
        )

    def test_documents_have_shared_catalog_and_next_stages(self):
        main=MAIN.read_text(encoding="utf-8")
        nav=NAV.read_text(encoding="utf-8")
        data=DATA.read_text(encoding="utf-8")
        self.assertIn("viewing_feature_catalog_stage42.csv",main)
        self.assertIn("viewing_screen_navigation.md",main)
        self.assertIn("viewing_data_requirements.md",main)
        for term in ("Stage43","Stage44","71","正式GUI","試験プレビュー"):
            self.assertIn(term,main)
        for term in ("year","school_id","player_id","competition_id","match_id","checkpoint"):
            self.assertIn(term,nav)
        for term in ("school_records","player_master","GameStats","MatchEvent","source_kind"):
            self.assertIn(term,data)

    def test_historical_observations_are_not_scored_simulation_records(self):
        text="\n".join(path.read_text(encoding="utf-8") for path in (MAIN,NAV,DATA))
        for mention in (
            "公式", "二次", "48", "25", "32", "未確認",
            "FMT025", "任意順位戦", "合算", "SQLite",
        ):
            self.assertIn(mention,text)
        status={x["feature_id"]:x for x in read_catalog()}
        self.assertEqual(status["VIEW-TOUR-005"]["current_state"],"preview_only")
        self.assertEqual(status["VIEW-MATCH-007"]["data_readiness"],"needs_new_data")
        self.assertEqual(status["VIEW-UX-002"]["current_state"],"future_candidate")

    def test_catalog_injected_unsupported_claims_are_rejected(self):
        rows=read_catalog()
        for field,value in (
            ("current_state","production_verified"),
            ("priority_draft","P-0"),
            ("reference_path","docs/design/not_really_present.md"),
            ("data_readiness","verified_official_draw"),
        ):
            altered=[dict(x) for x in rows]
            altered[0][field]=value
            self.assertTrue(audit_catalog(altered),field)

    def test_duplicate_features_cannot_enter_design_baseline(self):
        rows=read_catalog()
        altered=rows+[dict(rows[0])]
        self.assertTrue(any("duplicate feature ID" in e for e in audit_catalog(altered)))


if __name__=="__main__":
    unittest.main()
