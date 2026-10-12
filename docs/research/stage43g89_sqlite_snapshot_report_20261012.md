# Stage 43G-89：複数SQLiteの保存・snapshot整合性監査報告

2026-10-12（日本時間）。Issue #233。[設計](stage43g89_sqlite_snapshot_design_20261012.md)。基点：main `09f80cf42d173988231992b57954027abd99e2da`。新規ブランチ：`codex/stage43g89-sqlite-snapshot-audit`。

## 結果と実問題

**実際のv2保存APIで、appendとsealが両方成功して封印台帳と原本の試合集合がずれる欠陥を再現し修正した。** 一方、学校検索で混合した不整合な学校試合結果の成功は今回のスケジュールでは確認しなかった。byte同一renameを最終stat後に挿入すると修正前readerは成功したが、その旧snapshotは独立入力oracleと一致していた。保存不整合、変更検知漏れ、一貫した旧結果の許容を区別する。

修正前の保存競合は次の確定的順序で再現した。既存sealed年度G10099を残し、calendar登録済みG10100に完全Aを1試合appendしてactiveにする。

| 順序 | seal先行 | appendの状態確認先行 |
|---|---|---|
| 1 | sealがactive/全payload/ledger1試合を確認してEvent待ち | appendがactiveを確認し、既存match照会直前でEvent待ち |
| 2 | 別threadのappendが2試合目をcommitして完了 | 別threadのsealが1試合として封印commitして完了 |
| 3 | sealを解放。headerに件数1/旧SHAを書きcommit成功 | appendを解放。2試合目INSERT/commit成功 |
| oracle | 原本2試合/header1試合/ledger SHA不一致 | sealed年度への追加が成功し、同じ不一致 |
| 修正後 | appendはBEGIN IMMEDIATEで待ち、seal完了後にsealedを確認して拒否 | sealはBEGIN IMMEDIATEで待ち、append完了後に2試合を確認。expected_count=1を拒否、正しい2で再seal成功 |

独立SQL oracleは `competition_id,match_id,record_sha256` を整列し、canonical JSONをhashlib.sha256で計算する。productionの `_ledger` を期待値生成に使っていない。修正前の合成fixtureでは原本とheaderのSHAが異なり、件数2対1だった。具体的なSHA値は公開記録から除外する。readerはその保存を検出して拒否するため、修正前でも不正な台帳を有効として表示するという主張はしない。

本修正はappend/sealへBEGIN IMMEDIATEを各1箇所追加し、v2ファイル内の状態確認と書込を同一transactionにした。新しい共通永続lock・manifest・ATTACH・schema移行は導入していない。索引生成はsource/calendarの固定snapshotと独立watcherを共有し、観測した生成中commitを公開前に拒否する。最終監視はstat→data_version→statでrenameの確認窓を補強した。

## 競合スケジュール表

各注入は別thread・別SQLite接続で実行。Event/Barrier/SQL境界を用い、sleepなし、全待ち10秒上限。全fixtureは一時DB。source、calendar、2つの世紀索引を別ファイルとして試験した。

| 種類 | subtest数 | 結果・oracle |
|---|---:|---|
| 各file snapshot直前/直後のWAL commit × page/strict | 16 | watcherまたは元データ照合で拒否 |
| connection確保後・prepare直前のcommit | 4 | source/calendar/索引1/索引2の変更を拒否 |
| COUNT実行後・ページ取得前のcommit × page/strict | 4 | 件数/表示は固定snapshot、最終監視で成功結果を拒否 |
| 各file最終watcherの直前/直後commit | 8 | 直前は拒否、直後は一貫した旧学校結果を許容 |
| snapshot後/最終stat後watcher前のrename | 8 | 全4fileを拒否。byte同一差替えでもinode差を確認 |
| WAL PASSIVE checkpoint | 4 | 内容世代を変えないcheckpointは許容、入力oracle一致 |
| 実API calendar登録/append/sealの検索中commit | 3 | G10099のみの読取でも、別年度への観測更新を拒否 |
| raw SQLでcalendar/source/索引を段階的破壊 | 3 | 混合成功なし。通常の保存APIが許可する更新ではない |
| 索引生成中source/calendarのWAL commit | 2 | 未公開・一時DB削除。修正前は変更拒否なし |
| 同一matchの同時append：同一/異なる完全A | 2 | 同一は1挿入/1無挿入、異なるものは1成功/1競合拒否 |
| **subtest計** | **54** | JSONに各スケジュールと合否を保存 |

これにsubtest外9件を加え、新規19 unittest。subtest外は上記実writer競合2件、段階的年次保存1件、公開target衝突1件、監視完了後append1件、rollback journal1件、安定projection/SHA1件、別slot切替1件、実Tk1件。安定projectionは68件・30/30/8、0件校、2大会、offset超過を入力oracleで照合し、原本/calendar/旧A/2索引SHA不変を確認する。実Tkでは次ページ取得中のWAL commitを検出し、前ページ・offset・年度・検証scope・明示索引選択を維持する。

## ローカル実測・再現ログ

Python 3.12.14 / SQLite 3.53.1 / クラウドLinux、共有CPU quota 2 core。ローカル全unittest・関東E2Eを並行実行した時間を含むため、性能順位や改善倍率を示す値ではない。

| 検証 | 実測結果 |
|---|---|
| 修正前production＋初期競合回帰 | 16件 / 5.984秒、期待した8 failure（保存2、builder2、rename4）、errorなし |
| 修正後Stage89単独・実Tk | 19件 / 7.880秒、54 subtest、失敗0、スキップ0 |
| Stage79/83/84/85/86/87/88/89・実Tk | 79件 / 23.323秒、失敗0、スキップ0 |
| 全Python unittest | 2,020件 / 829.883秒、失敗0、41スキップ（従来40＋実Tk新規1、専用CIでは実行） |
| 関東17校E2E | 2件 / 319.540秒、失敗0、スキップ0 |

記録：[修正前再現ログ](../../audits/phase2/stage43g89/baseline_reproduction_20261012.log)、[修正後JSON](../../audits/phase2/stage43g89/concurrency_20261012.json)、[修正後ログ](../../audits/phase2/stage43g89/concurrency_20261012.log)、[全関連回帰JSON](../../audits/phase2/stage43g89/regression_20261012.json)。修正前ログは大きな学校page返値dumpのみ省略し、assertionと差分を残した。初期16件から同時重複append・slot・Tkの3件を追加し最終19件となったため、修正前後の件数差を速度比較に使わない。

## 保証する範囲と残る判断

- v2単一DBの実API append/sealにおける封印状態・原本集合・ledgerのtransaction整合性を修正。calendar/完全A/ledger/全所属/SHAの検証水準とAPI返値を維持。
- 学校検索の各file固定snapshot、COUNTと表示の一致、strictで表示外/他校を含む全原本・全所属照合、観測したWAL commit/renameの拒否を確認。
- 最終監視直後/全監視後に更新しても、一貫した旧snapshotが返る場合は合格とする。最新版・全file同一時点・全保存世代の原子性は保証しない。
- 索引生成の監視終了からhard-link公開までの間にwriterが入ると、旧projectionの索引が公開され得る。次回readerは新年度/ledger/出典を再検証しstaleを拒否。索引の自動承認は行わない。
- calendar登録だけ完了した未使用年度は過去の結果を変えず、active年度・封印後の古い索引はfail-closed。既存sealed原本/planの書換えは実APIでは禁止。
- raw同inode上書き、ABA rename、crash/外部restore、全シャード一括成功、バックアップ世代一致は未保証。manifest/共通lock/backup/ATTACHは [ADR-030（提案）](../adr/ADR-030-v2-multifile-generation-snapshot-proposal.md) に比較と必要試験を残した。

BEGIN IMMEDIATEはsealの全SHA検証中もv2 writer予約を保持する。並行writerは既存SQLite timeout内で待つかbusyを返し、勝手にretryしない。これは整合性のための最小変更で、長時間sealの運用費用は別の性能/運用監査が必要。calendar同一年度の同時INSERTはunique制約で一方が失敗し得るが、異なる既存planを上書きする経路はない。

マスター106CSVと既存セーブ4ファイルのSHA一致を確認し、[保護ファイル記録](../../audits/phase2/stage43g89/protected_files_20261012.json)に件数・一致結果を保存した。既存セーブの具体的path・SHA一覧は外部公開せずローカルで保持する。SQLite/CSVは検証前から、既存saveの3JSONは最終検証完了前に追加したbaselineから照合。正式セーブをテストへ入力しない。

既存セーブ・旧A・完全A原本・マスターを移行/変更しない。年数無制限の方針を維持し、100年度/索引と32シャード/検索は操作制限のまま。Tkは試験GUI、独立索引は手動承認。全国100/200年の連続実進行・大幅な性能改善は本Stageの成果に含めない。

## CIと再現コマンド

専用 `career-v2-sqlite-concurrency.yml` は新規19件とStage79/83〜88の60件を実Tkで実行し、JSON/logをartifactに保存。全Python 3.12と関東17校は既存CIを維持。最終headに対するCIの完了結果・head SHA・URLはPR本文を正本として記録する（CI待ちの時点を成功と扱わない）。成功確認後もPRをマージせずレビュー待ちにする。

初回CIはテスト成功後も成果物を実際にダウンロードしたところ、標準出力リダイレクトのJSONにテストログが混ざっていた。`--json-output` で新規ファイルへ直接保存し、CI内でJSON decode、19件/54 subtest/スキップ0/全成功をassertする。ログは別ファイルに保存し、既存出力ファイルの上書きは拒否する。

```bash
xvfb-run -a python -m phase2_engine.career_v2_sqlite_concurrency_audit
for stage in 79 83 84 85 86 87 88 89; do
  xvfb-run -a python -m unittest discover -s tests -p "test_stage43g${stage}_*.py" -v
done
KOKOSIM_SKIP_STAGE43G10_E2E=1 python -m unittest discover -s tests -v
python -m unittest discover -s tests -p 'test_stage43g10_full_kanto17_e2e.py' -v
```

修正前の保存競合だけを再現する場合は、別の一時checkout/worktreeにmain基点のproductionを置き、本PRのaudit helperとtest fileをコピーして、`Stage43G89ConcurrencyTests.test_append_during_seal_cannot_invalidate_committed_ledger` と `test_seal_after_append_status_check_cannot_be_overtaken` を実行する。両方が失敗しraw封印oracleが不一致となる。正式セーブを指定して再現しない。

次Stage候補は43G-90：世代単位backup/restore・公開契約のADR評価とkill/restart試験。まず全file同一世代が必要な製品要件を確定し、既存保存の参照・移行承認を得てから採用案を決める。
