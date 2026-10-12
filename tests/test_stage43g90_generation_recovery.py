"""Disposable full-A generations: raw oracle, actual kill/WAL, explicit refusal."""
from contextlib import closing
import json
from pathlib import Path
import random
import shutil
import sqlite3
import unittest
from unittest.mock import patch

from phase2_engine.career_calendar_v2 import CareerCalendarV2Archive, explicit_sandbox_plan
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.career_v2_generation_recovery_audit import (
    GenerationLab, LabRosterArchive, Refused, canonical, kill_generation, raw_oracle, ro, sha,
    sql_fingerprint, COMPETITIONS, SEED, _box_score,
    read_v2_school_century_page,
)


class Stage43G90GenerationTests(unittest.TestCase):
    def lab(self, **dimensions):
        return self.enterContext(GenerationLab(**dimensions))

    def future(self, lab, *, append=True, seal=True):
        CareerCalendarV2Archive(lab.f.calendar).record(explicit_sandbox_plan(10100,
            {COMPETITIONS[0]: ["04-01"]}, approved_for_fictional_game=True))
        row = _box_score(10100, "KILL90", COMPETITIONS[0], *lab.f.schools[:2], "04-01", random.Random(SEED))
        if append:
            lab.f.archive.append(10100, row)
        if append and seal:
            lab.f.archive.seal_year(10100, expected_match_count=1)
        return row

    def add_expectation(self, lab, row):
        for school, opponent, own, against in (
            (row["team1_id"], row["team2_id"], row["team1_score"], row["team2_score"]),
            (row["team2_id"], row["team1_id"], row["team2_score"], row["team1_score"])):
            lab.expected[school].append(dict(year=10100, competition_id=row["competition_id"],
                match_id=row["match_id"], game_day_token=row["game_day_token"], school_id=school,
                opponent_school_id=opponent, runs_for=own, runs_against=against,
                result_for_school="win" if own > against else "loss"))

    def exported(self, lab, label="old"):
        lab.approve(label)
        return lab.backup(label, include_indexes=bool(lab.indexes))

    def test_restore_full_a_boundary_30_30_8_zero_two_filters_and_index_rejection(self):
        lab = self.lab(rounds=34)
        lab.build(approved=True)
        before = {k: sha(p) for k, p in lab.roles.items()}
        published = self.exported(lab)
        restored = lab.restore(published, "old")
        copied = sorted(restored.glob("fictional_v2_school_read_index*.sqlite3"))
        with self.assertRaisesRegex(ValueError, "source|metadata"):
            lab.read(restored, "old", copied)
        with self.assertRaises(Refused):
            lab.build(restored=restored)
        indexes = lab.build(restored=restored, approved=True)
        result = lab.read(restored, "old", indexes)
        self.assertEqual([30, 30, 8, 0], result["first_school_page_sizes"])
        self.assertEqual(before, {k: sha(p) for k, p in lab.roles.items()})
        self.assertEqual(lab.approvals["old"]["proofs"], {k: sql_fingerprint(p) for k, p in lab.restored_roles(restored).items()})
        # Roster/identity history is a separate real contract from synthetic box-score IDs.
        original = LabRosterArchive(lab.roster)
        recovered = LabRosterArchive(lab.restored_roles(restored)["roster"])
        for school in lab.f.schools[:2]:
            roster = original.roster(10099, school)
            self.assertEqual(roster.to_dict(), recovered.roster(10099, school).to_dict())
            for player in roster.players:
                self.assertEqual(original.player_history(player.player_id), recovered.player_history(player.player_id))

    def test_retained_old_and_new_sealed_generations_are_complete(self):
        lab = self.lab(schools=2, years=1, rounds=2)
        old = self.exported(lab)
        old_sha = {p.name: sha(p) for p in old.iterdir()}
        row = self.future(lab)
        self.add_expectation(lab, row)
        new = self.exported(lab, "new")
        for label, path, count in (("old", old, 2), ("new", new, 3)):
            with self.subTest(generation=label):
                recovered = lab.restore(path, label)
                roles = lab.restored_roles(recovered)
                self.assertEqual(count, raw_oracle(roles["source"], roles["calendar"], lab.approvals[label]["expected"]))
                self.assertGreater(lab.read(recovered, label, lab.build(approved=True, restored=recovered))["verified_queries"], 0)
        self.assertEqual(old_sha, {p.name: sha(p) for p in old.iterdir()})

    def test_fixture_roster_writer_closes_handle_without_waiting_for_gc(self):
        lab = self.lab(schools=2, years=1, rounds=1)
        archive = LabRosterArchive(lab.roster)
        roster = archive.roster(10099, lab.f.schools[0])
        connection = sqlite3.connect(lab.roster)
        connection.row_factory = sqlite3.Row
        self.addCleanup(connection.close)
        with patch.object(CareerRosterArchive, "_connect", return_value=connection):
            self.assertFalse(archive.save_initial_roster(roster)["inserted"])
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")

    def test_sources_only_backup_omits_derived_indexes_and_requires_explicit_rebuild(self):
        lab = self.lab(schools=2, years=1, rounds=1)
        lab.build(approved=True)
        lab.approve("old")
        published = lab.backup("old")
        manifest = lab.validate(published, "old")
        self.assertEqual(set(lab.roles), set(manifest["files"]))
        restored = lab.restore(published, "old")
        with self.assertRaises(ValueError):
            lab.read(restored, "old", [])
        with self.assertRaises(Refused):
            lab.build(restored=restored)
        self.assertGreater(lab.read(restored, "old", lab.build(approved=True, restored=restored))["verified_queries"], 0)

    def test_unapproved_candidate_and_changed_after_approval_refused(self):
        lab = self.lab(years=1)
        with self.assertRaises(KeyError):
            lab.backup("missing")
        lab.approve("old")
        self.future(lab, append=False)
        with self.assertRaisesRegex(Refused, "changed"):
            lab.backup("old")
        self.assertFalse((lab.root / "oldpublished").exists())

    def test_actual_process_kill_at_each_sqlite_commit_boundary(self):
        for stage in ("calendar", "append", "seal", "index"):
            for boundary in ("commit_before", "commit_after"):
                with self.subTest(stage=stage, boundary=boundary):
                    lab = self.lab(schools=2, years=1, rounds=1)
                    old = self.exported(lab)
                    if stage in ("append", "seal", "index"):
                        self.future(lab, append=stage != "append", seal=stage == "index")
                    # Keep the WAL reader open so child death cannot checkpoint on last close.
                    target = lab.f.calendar if stage == "calendar" else lab.f.source
                    db = self.enterContext(closing(sqlite3.connect(target)))
                    self.assertEqual("wal", db.execute("PRAGMA journal_mode=WAL").fetchone()[0])
                    db.execute("PRAGMA wal_autocheckpoint=0")
                    db.execute("BEGIN")
                    db.execute("SELECT name FROM sqlite_master").fetchall()
                    row = lab.kill_writer(stage, boundary)
                    lab.validate(old, "old")  # surviving published generation stays complete
                    with closing(ro(target)) as restarted:
                        self.assertEqual([("ok",)], restarted.execute("PRAGMA integrity_check").fetchall())
                        if stage == "calendar":
                            present = restarted.execute("SELECT COUNT(*) FROM sandbox_year_plans WHERE game_year=10100").fetchone()[0]
                            self.assertEqual(int(boundary == "commit_after"), present)
                        elif stage == "append":
                            present = restarted.execute("SELECT COUNT(*) FROM v2_option_a_matches WHERE year=10100").fetchone()[0]
                            self.assertEqual(int(boundary == "commit_after"), present)
                        elif stage == "seal":
                            status = restarted.execute("SELECT status FROM v2_game_years WHERE year=10100").fetchone()[0]
                            self.assertEqual("sealed" if boundary == "commit_after" else "active", status)
                        else:
                            self.assertFalse(list(lab.root.glob("*killed.sqlite3")))
                    if stage == "index" or (stage == "seal" and boundary == "commit_after"):
                        self.add_expectation(lab, row)
                        self.assertEqual(2, raw_oracle(lab.f.source, lab.f.calendar, lab.expected))
                    elif stage == "calendar" or (stage == "append" and boundary == "commit_before"):
                        self.assertEqual(1, raw_oracle(lab.f.source, lab.f.calendar, lab.expected))
                    if stage == "append" and boundary == "commit_after":
                        self.assertGreater(Path(str(target) + "-wal").stat().st_size, 0)
                        with self.assertRaisesRegex(Refused, "active"):
                            raw_oracle(lab.f.source, lab.f.calendar, lab.expected)

    def test_actual_index_publication_kill_before_after(self):
        for boundary in ("publish_before", "publish_after"):
            with self.subTest(boundary=boundary):
                lab = self.lab(schools=2, years=1, rounds=1)
                before = {k: sha(p) for k, p in lab.roles.items()}
                lab.kill_writer("index", boundary)
                indexes = list(lab.root.glob("*killed.sqlite3"))
                self.assertEqual(int(boundary == "publish_after"), len(indexes))
                self.assertEqual(before, {k: sha(p) for k, p in lab.roles.items()})
                if indexes:
                    result = read_v2_school_century_page(lab.f.source, lab.f.calendar, indexes,
                        lab.f.schools[0], start_year=10099, end_year=10099, verify_scope="selected_years")
                    self.assertEqual(1, result["total"])
                    self.assertEqual(lab.expected[lab.f.schools[0]],
                        [{k: row[k] for k in lab.expected[lab.f.schools[0]][0]} for row in result["records"]])
                # Published candidate is not activated by the experiment.
                self.assertEqual([], lab.indexes)

    def test_generation_kill_at_backup_restore_copy_manifest_and_publication(self):
        for stage, boundaries in (
            ("backup", ("source_copy_before", "source_copy_after", "calendar_copy_after",
                "roster_copy_after", "manifest_before", "manifest_after", "publish_before", "publish_after")),
            ("restore", ("source_copy_before", "source_copy_after", "calendar_copy_after",
                "roster_copy_after", "manifest_before", "manifest_after", "read_before"))):
            for boundary in boundaries:
                with self.subTest(stage=stage, boundary=boundary):
                    lab = self.lab(schools=2, years=1, rounds=1)
                    old = self.exported(lab)
                    old_shas = {p.name: sha(p) for p in old.iterdir()}
                    lab.approve("new")
                    if stage == "restore":
                        lab.backup("new")
                    kill_generation(lab, "new", stage, boundary)
                    lab.validate(old, "old")
                    candidate = lab.root / ("newpublished" if stage == "backup" else "newrestored")
                    complete = boundary == "publish_after" if stage == "backup" else boundary in ("manifest_after", "read_before")
                    if complete:
                        lab.validate(candidate, "new")
                    else:
                        with self.assertRaises(Refused):
                            lab.validate(candidate, "new")
                    self.assertEqual(old_shas, {p.name: sha(p) for p in old.iterdir()})

    def test_wal_uncheckpointed_backup_includes_committed_complete_a(self):
        lab = self.lab(schools=2, years=1, rounds=1)
        db = self.enterContext(closing(sqlite3.connect(lab.f.source)))
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA wal_autocheckpoint=0")
        db.execute("BEGIN")
        db.execute("SELECT * FROM v2_game_years").fetchall()
        row = self.future(lab)
        self.add_expectation(lab, row)
        self.assertGreater(Path(str(lab.f.source) + "-wal").stat().st_size, 0)
        naive = lab.new_dir("naive") / lab.f.source.name
        shutil.copyfile(lab.f.source, naive)
        with self.assertRaises(Refused):
            raw_oracle(naive, lab.f.calendar, lab.expected)  # main alone misses committed WAL content
        published = self.exported(lab)
        restored = lab.restore(published, "old")
        self.assertEqual(2, raw_oracle(lab.restored_roles(restored)["source"], lab.restored_roles(restored)["calendar"], lab.expected))
        self.assertTrue(all(p.stat().st_size == 0 for p in restored.glob("*-wal")))

    def test_disk_full_short_copy_rename_and_existing_publication_refuse(self):
        for fault in ("enospc", "shortcopy", "rename", "existing"):
            with self.subTest(fault=fault):
                lab = self.lab(schools=2, years=1, rounds=1)
                old = self.exported(lab)
                before = {k: sha(p) for k, p in lab.roles.items()}
                lab.approve("new")
                if fault == "existing":
                    target = lab.new_dir("newpublished")
                    (target / "guard").write_text("existing target")
                with self.assertRaises((OSError, Refused, sqlite3.DatabaseError)):
                    lab.backup("new", fault=fault)
                lab.validate(old, "old")
                self.assertEqual(before, {k: sha(p) for k, p in lab.roles.items()})
                if fault == "existing":
                    self.assertEqual("existing target", (target / "guard").read_text())

    def test_stale_manifest_sha_and_calendar_source_roster_generation_drift(self):
        for fault in ("stale", "sha", "calendar", "source", "roster", "manifestonly", "missing", "traversal"):
            with self.subTest(fault=fault):
                lab = self.lab(schools=2, years=1, rounds=1)
                published = self.exported(lab)
                attacked = lab.new_dir("attacked")
                for p in published.iterdir():
                    shutil.copyfile(p, attacked / p.name)
                manifest_file = attacked / "manifest.json"
                manifest = json.loads(manifest_file.read_text())
                if fault == "stale":
                    manifest["generation"] = "unknown"
                elif fault == "sha":
                    manifest["files"]["source"]["sha256"] = "bad"
                elif fault == "missing":
                    del manifest["files"]["roster"]
                elif fault == "traversal":
                    manifest["files"]["source"]["name"] = "../fictional_option_a_v2.sqlite3"
                elif fault == "manifestonly":
                    manifest["proofs"]["source"] = "forged"
                else:
                    path = attacked / manifest["files"][fault]["name"]
                    with closing(sqlite3.connect(path)) as db:
                        sql = {"source": "UPDATE v2_game_years SET status='active'",
                            "calendar": "UPDATE sandbox_year_plans SET content_sha256='bad'",
                            "roster": "UPDATE career_player_identities SET identity_sha256='bad'"}[fault]
                        db.execute(sql)
                        db.commit()
                    # Attacker recomputes file SHA; independent approval remains unchanged.
                    manifest["files"][fault]["sha256"] = sha(path)
                manifest_file.write_text(canonical(manifest))
                with self.assertRaises(Refused):
                    lab.validate(attacked, "old")
                lab.validate(published, "old")

    def test_cross_restore_of_valid_old_new_source_calendar_is_refused(self):
        lab = self.lab(schools=2, years=1, rounds=1)
        old = self.exported(lab)
        self.add_expectation(lab, self.future(lab))
        new = self.exported(lab, "new")
        for label, base, other, role in (("old", old, new, "calendar"), ("new", new, old, "calendar")):
            with self.subTest(generation=label):
                attacked = lab.new_dir(label + "mixed")
                for p in base.iterdir():
                    shutil.copyfile(p, attacked / p.name)
                manifest_file = attacked / "manifest.json"
                manifest = json.loads(manifest_file.read_text())
                name = manifest["files"][role]["name"]
                shutil.copyfile(other / name, attacked / name)
                manifest["files"][role]["sha256"] = sha(attacked / name)
                manifest_file.write_text(canonical(manifest))
                with self.assertRaises(Refused):
                    lab.validate(attacked, label)
                lab.validate(base, label)

    def test_foreign_slot_and_indexes_refused(self):
        a = self.lab(schools=2, years=1, rounds=1)
        b = self.lab(schools=2, years=1, rounds=1)
        bindexes = b.build(approved=True)
        published = self.exported(a)
        with self.assertRaisesRegex(Refused, "foreign"):
            a.validate(published, "old", slot="laboratory-slot-B")
        restored = a.restore(published, "old")
        with self.assertRaisesRegex(ValueError, "local"):
            a.read(restored, "old", bindexes)
        with self.assertRaises(Refused):
            a.validate(b.root, "old")

    def test_interleaved_multidb_backup_is_not_same_generation(self):
        lab = self.lab(schools=2, years=1, rounds=1)
        lab.approve("old")
        def after_source(point):
            if point == "source_copy_after":
                self.future(lab)
        with self.assertRaisesRegex(Refused, "generations|changed"):
            lab.backup("old", hook=after_source)
        self.assertFalse((lab.root / "oldpublished").exists())

    def test_restore_collision_and_outside_paths_have_no_side_effect(self):
        lab = self.lab(schools=2, years=1, rounds=1)
        published = self.exported(lab)
        recovered = lab.restore(published, "old")
        before = {p.name: sha(p) for p in recovered.iterdir()}
        with self.assertRaises(FileExistsError):
            lab.restore(published, "old")
        with self.assertRaises(Refused):
            lab.local(lab.root.parent / "not-owned")
        self.assertEqual(before, {p.name: sha(p) for p in recovered.iterdir()})


if __name__ == "__main__":
    unittest.main()
