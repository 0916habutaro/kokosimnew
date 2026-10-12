# Stage 43G-90：世代backup/restore・障害復旧監査報告

2026-10-12（日本時間）。Issue #235。main `07b456e5ef6c1e803ddd3880c16f2a67f638307e`から独立ブランチ。対象は[設計書](stage43g90_generation_recovery_design_20261012.md)と[ADR-031（未採用）](../adr/ADR-031-generation-backup-recovery-evaluation.md)。ADR-030、Stage87〜89と実装を調査した。

## 結論

複数SQLiteの必須正本集合・世代承認・復旧後の公開条件を先に定義し、私有一時fixtureでbackup/restoreと確定的障害注入を監査した。**productionの新保存形式・自動復元・移行・GUI統合は導入していない。** 学校索引は原本/calendar絶対pathへ束縛され、復元先へコピーしたものは拒否された。SQLite backupは未checkpoint WALのcommit済み内容を回収したが、DB毎のbackup間に次年度保存を挟むと同世代集合として拒否された。どちらも製品側に新しい公開契約を必要とする理由である。

## 保証済み（本実験の範囲）

- 14 unittest、41 subtestスケジュール。実SQLite、WAL、spawn子プロセスとPipe到達通知、process.kill、新接続での再検証を使用。ランダムsleepなし。commit前後8、index公開前後2、backup/restore境界15の計25 killスケジュール。
- 独立入力oracleとraw SQL/SHAによる全完全A・calendar・年次ledgerの一致。復元先でstrict学校読取を再検証し、G10099/G10100、68件30/30/8、0件学校、2大会filter、offset超過が一致。
- 異内容の旧・新封印世代を両方保持し復元。旧公開世代のfile SHAを維持。途中状態はactive/欠落/manifestなしとして拒否。完全状態だけを公開/検証する。
- SHA不正・古いmanifest・manifestだけ偽造・原本/calendar/roster改ざん・正しい旧/新calendarの取り違え・必須正本欠落・異slot・foreign索引・path逸脱を拒否。file SHAを再計算しても独立承認proof不一致を拒否する。
- 未承認候補backup、承認後に変更した候補、既存target、restore先再使用、rename失敗、ENOSPC注入、コピー半分truncateを拒否。旧公開集合/既存target guardを保持する。
- backup APIでWAL込み論理snapshotを独立コピー。WALを無視してmainだけコピーする比較では新世代input oracleと不一致になることを確認。復元後にro接続が作る空WALはcopyされた元WALとは区別する。
- 必須正本だけのbackupも成立。学校索引をコピーした場合はmetaを書き換えず拒否し、明示再生成後にのみstrict読取。索引の生成/候補承認/利用を自動化しない。
- 別旧A封印guard、2校のロスターsnapshotと40名のplayer_history/identityを復元先で照合。合成試合の選手IDとこのロスターの帰属一致は主張しない。

private manifestと別のメモリ上approval anchorを使う候補での整合性検証である。製品の永続世代保証ではない。backup/restoreの拒否後に残った一時artifactを自動的に修復/削除/昇格させるコードはない。TemporaryDirectoryの実験終了時cleanupだけが行われる。

## 実負荷の範囲・実測

[小規模JSON](../../audits/phase2/stage43g90/small_20261012.json)、[全国短年度JSON](../../audits/phase2/stage43g90/national3746_20261012.json)、[200年度疎JSON](../../audits/phase2/stage43g90/sparse200_20261012.json)。Python3.12.14 / SQLite3.53.1 / Linux。seed `2026101201`。全て実APIでappend/sealする合成完全Aであり、実際の全国100/200年連続大会実行ではない。

| fixture | 保存試合数 | 元集合MiB（索引込） | 観測ピークMiB | backup ms（2回） | restore ms（2回） | 明示index再生成 ms（2回） |
|---|---:|---:|---:|---|---|---|
| 4校×2年度×34試合/校 | 136 | 1.414 | 7.356 | 76.805 / 205.152 | 48.476 / 145.018 | 30.401 / 95.842 |
| 全国3,746校×1年度×2試合/校 | 3,746 | 33.731 | 172.828 | 2100.941 / 1925.189 | 1761.175 / 1354.257 | 1059.293 / 891.759 |
| 2校×200保存年度×2試合/校 | 400 | 3.988 | 20.650 | 612.094 / 273.012 | 169.143 / 189.090 | 120.150 / 125.866 |

ピークは元集合＋2保持backup＋2復元dir＋新索引、manifest、観測時のWAL/SHM/tempの**ファイルサイズ合計の観測最大**。liveのみ/単一復元のピークとは異なる。実際のallocated blocks、RSS、FS圧縮、コピー内部の瞬間ピークではない。2ラベルの容量測定は同内容集合の保持で、異なる世代へのゲーム進行を測らない。異内容の旧/新整合性は別回帰に分離した。

backup時間は事前approval後のlive確認、SQLite backup、raw検証、manifest作成/新規dir公開を含む。restore時間は元bundleの事前検証後、新規dir copyから復元後再検証まで。index再生成・strict読取は別時間。全国fixtureの45検索（全原本・所属検証を繰り返す）は46,489.665 / 43,391.682ms。これを単一学校1ページの復旧SLOに読み替えない。小規模は45検索、200年度は33検索。OS/SQLiteキャッシュを排除せず、測定は他のテストと並行した共有環境の2サンプルで、性能比較の統制実験ではない。

完全Aはソロ本塁打だけの簡略成績、各試合18打者/2投手/9イニング。継投・交代・延長・コールド・実進行・全国校の長期ロスターを含まないため、実セーブ容量の下限寄りサンプルである。全国fixtureもロスターは別2校初期snapshotのみ。200保存年度は10099〜10298の連続保存年度を疎密度で作り3索引に分け、保存年数上限を導入しない。

## 未保証

OS停止/電源断、Windows open-handle/antivirus干渉、directory fsync耐久性、NFS/ネットワークFS、同inode raw改変/ABA、全スケジュールの数学的原子性、並行target作成への汎用no-clobber公開、永続approval crash/署名/key rotationは未保証。実ディスク満杯は行わず、ENOSPCを確定境界で注入した。ランダム故障や長期間soakを保証済みとしない。

今回のprototypeは自己生成fixtureの集合だけを処理し、既存製品セーブの全依存inventory/live JSON/設定互換の復元は実装しない。共通lock/ATTACH方式は設計比較のみで、方式間の同条件容量・時間比較は未実測。SQLite backup単体で複数DBの同時点保証を得たとはしない。roster/player_historyのコピー一致と試合選手の帰属保証は別である。

## 未採用設計・移行の要否

[ADR-031](../adr/ADR-031-generation-backup-recovery-evaluation.md)はProposed。原本/派生分離、必須正本集合、承認anchor、immutable generation/publication、共通lock、SQLite backup、ATTACHの比較をまとめた。製品manifest/lock、journal変更、schema/migration、旧history削除、GC、自動restore/promotion、索引の自動承認は未実装。

原本を新規dirへコピーする実験はschema移行を必要としない。一方、製品でgeneration identity/選択参照を導入する場合はwriter/reader/backup経路の契約変更と既存セーブ移行評価が必要。学校索引を必須同世代として別pathで再利用するには既存出典契約の移行が必要になる。候補案は復元後不使用/新規明示再生成としてpath契約を維持する。今回は移行不要な監査追加のみ。

## 検証記録とCI

専用 `.github/workflows/career-v2-generation-recovery.yml` はUbuntu/Windows・Python3.12で14回帰/41subtestと小規模測定を必須とする。全国3,746校と200年度はworkflow_dispatchへ分離。整合性oracle/SHA/件数/不変性を合格条件にし、固定ms閾値は置かない。実行済みの詳細は[障害回帰JSON](../../audits/phase2/stage43g90/fault_regressions_20261012.json)。

ローカルPython3.12の関東17校E2Eは2テスト/499.899秒で成功。新規最終回帰は14テスト/41subtest/19.671秒で全成功・スキップ0。全Python unittestの完了結果はPR本文に記録し、ローカル結果とGitHub CIを区別する。最終headのGitHub専用CI・全Python3.12 unittest・関東17校E2Eの結果/URLはPR本文に記録し、成功確認後も未マージでレビュー待ちにする。

既存セーブとマスター106CSVのprivate SHAは検証前に取得した。最終一致結果は[保護ファイル記録](../../audits/phase2/stage43g90/protected_files_20261012.json)へ件数・一致だけ記載する。セーブの具体的filename/fullpath/SHA一覧はGitHubへ追加しない。既存saveをテストの入力に使わない。

```bash
python -m phase2_engine.career_v2_generation_recovery_audit --regressions --json-output /tmp/stage90-faults-new.json
python -m phase2_engine.career_v2_generation_recovery_audit --profile small --json-output /tmp/stage90-small-new.json
python -m phase2_engine.career_v2_generation_recovery_audit --profile national3746 --json-output /tmp/stage90-national-new.json
python -m phase2_engine.career_v2_generation_recovery_audit --profile sparse200 --json-output /tmp/stage90-sparse-new.json
KOKOSIM_SKIP_STAGE43G10_E2E=1 xvfb-run -a python -m unittest discover -s tests -v
python -m unittest discover -s tests -p 'test_stage43g10_full_kanto17_e2e.py' -v
```

## 次Stageの判断事項

必要な機能と正本集合、旧Aとv2の運用接続、索引不使用時の利用条件、generation identity/公開参照、lock参加契約、署名/永続信頼元、電源断と両OSの耐久化、32シャード超の検証batch、年数無制限のまま保持容量とGC候補を利用者に提示し承認後に採用を決める。既存保存の形式変更や自動復元を本PRの成功で承認済みと扱わない。
