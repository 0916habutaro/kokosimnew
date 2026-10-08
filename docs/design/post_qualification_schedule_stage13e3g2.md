# Stage 13E-3G-2：代表確定後順位戦のスケジューラ・保存・閲覧接続

作成日：2026-10-08

## 実装の目的と境界

3G-1で実装した`RankingOnlyEventRuntime`を、2026年度大会の`ScheduledCompetitionRuntime`と`LiveSeasonDependencyRuntimeState`から、**明示的に登録して閲覧・進行できるようにする**。既存大会の予選勝者、シード権、MAIN出場校、後続大会への依存関係、完了・未完了判定は**一切変更しない**。

今回の追加試合は `ranking_only=True`、`qualifier_effect=none` であり、専用メソッドでのみ実行する。通常の `play_today()` では順位試合を勝手に実行しない。年度ごとの具体的日付が未確認なら、**日付を推測・生成せず、イベントを作成しない**。

## ランタイム

`phase2_engine/post_qualification_schedule.py`：`ScheduledRankingSidecar`

- 既に資格確定した`RankingOnlyEventRuntime`と、資格確定日`qualification_locked_on`、各ラウンドの明示日付`match_dates`を受け取る。
- FMT022沖縄型（2準決勝＋決勝）は各ラウンド2日を要求。決勝参加校は準決勝後にのみ可視化。
- FMT022徳島型（2ブロック決勝）とFMT025静岡・広島型（明示ペア順位決定戦）は1ラウンド分の日付を要求。
- 資格確定日以前、日付逆転、同日複数ラウンド、未設定日付、架空年度カードは拒否。
- `resolve_date(date, winners, scores=...)`は、その日に開催される全カードの勝者を明示する。任意のスコアを付ける場合は勝者との整合性を検証する。
- `cancel_remaining()`では未消化の順位戦だけ`canceled`とし、代表校決定・シード・大会完了を巻き戻さない。
- `snapshot()` / `from_snapshot()`で、日付、勝者、スコア、中止状態、次の試合を保存・再開する。

`phase2_engine/competition_schedule_runtime.py`：

- `attach_ranking_sidecar(sidecar)`：同一大会の明示イベントだけ登録。
- `matches_for_date(date)`と`ranking_matches_for_date(date)`：通常の試合と別に、追加順位戦を日付・校名・地区名・status付きで表示。
- `resolve_ranking_date(...)`：通常の`play_date`とは完全分離。
- `ranking_snapshot()` / `restore_ranking_snapshot(...)`：セーブ・ロード。
- `ScheduledCompetitionRuntime.is_complete`、`to_competition_run()`、`summary()`、通常の`completed_results()`は変更しない。

`phase2_engine/live_season_dependency.py`：

- `register_ranking_sidecar(competition_id, sidecar)`：既にactivateした大会に付与。
- `today_matches()`：順位試合も`ranking_only`と明示して閲覧可能。
- `play_today_rankings(winners_by_competition)`：通常の`play_today()`とは別に明示的に結果を入力。
- 依存解決・進出判定は既存`play_today`経路だけで行い、`play_today_rankings`からは呼び出さない。

## SQLiteと閲覧API

`BrowseRepository`に以下2表を非破壊追加：

- `ranking_event_snapshots`：年度・大会・地区ごとの途中セーブJSON
- `ranking_matches`：日付、対戦校ID、勝敗、スコア、予定/完了/中止

書込：`save_ranking_sidecar(year, sidecar)`（年度・大会・地区単位でトランザクション更新）

読込：`load_ranking_sidecar(year, competition_id, group_id)`

閲覧：`ranking_matches_on_date(year, date, competition_id="")`、`competition_ranking_matches(year, competition_id)`

既存`matches_by_date`、`competition_results`、`school_records`にはこれらの任意イベントを混入させず、勝敗・優勝・シード・選手統計の二重集計を回避する。閲覧GUIからは**別クエリで補足表示**する。正式GUIへの表示ウィジェット接続は今後の正式GUI段階で実施。

シーズン閲覧DBが再生成された場合、旧年度由来の任意順位戦は破棄する。既存DBのテーブルとデータは維持する。

## データの解決状態

3G-2で**任意の順位試合を日付指定で動かす仕組み**まで実装した。ただし2026年の静岡・広島各地区の「全順位戦の対戦校・実施日」をこの工程で登録するものではない。よって`RS2026025`・`RS2026026`の`design_pending`は残す。今後、全地区の実試合日とカードを正式資料に基づいて登録してから、必要な任意イベントだけを追加する。

## 確認手順

```bash
python -m unittest tests.test_stage13e3g2_scheduled_ranking -v
python -m unittest discover -s tests -p 'test_*.py' -v
```

新規テスト：日付検証、資格確定後の進行、未確定決勝の非公開、中止、部分セーブ再開、無資格校拒否、勝者とスコアの整合、SQLite日別・大会別閲覧、main完了判定不変、年間`today_matches`接続。

今後：必要なら`LiveSeasonDependencyRuntimeState`のスナップショット永続化へもsidecarのセーブを接続する。正式GUIの閲覧画面では順位戦に「代表確定後の追加試合」と明示する。
