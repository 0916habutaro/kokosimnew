# Stage 13E-3G-5：同一地区・複数日の順位決定戦と永続化

作成日：2026-10-08

## 問題と方針

3G-4で静岡春季西部地区 `SGR000105` に、4月4日と4月11日の順位決定戦が存在することが判明した。旧仕様では`ranking_sidecars[group_id]`が1件のみで、別日イベントを上書きまたは拒否し、`RankingOnlyEventRuntime._id()`も`stage_id + group_id + round`のみのため試合IDが衝突していた。

**解決**：`group_id + event_id` の二段階識別子を追加する。2026実証日付を使うFMT025の単日イベントでは、`event_id = DYYYYMMDD`とする。イベントIDは英数字と`-`・`_`に限定、64字以内。

- 例：`SGR000105@D20260404`（西部地区・4月4日）
- 例：`SGR000105@D20260411`（同地区・4月11日）
- 試合ID：`STG000182-SGR000105-POST_RANK-D20260404-R1-01`等
- 既存3G-1/3G-2の「event_idなし」の場合は旧ID`STG...-SGR...-POST_RANK-R1-01`を維持。

## ランタイム

1. `RankingOnlyEventRuntime.create(...,event_id="D20260404")`：試合IDにIDを含める。未指定なら完全に従来形式。
2. `ScheduledRankingSidecar.instance_key`：旧データはgroupのみ、新データは`group@event`。
3. `ScheduledCompetitionRuntime.ranking_sidecars`：同一groupに複数イベントを格納。重複キーと衝突する試合IDを拒否。日付閲覧、明示勝者入力、順位戦snapshot／restoreをeventキーで扱う。
4. `LiveSeasonDependencyRuntimeState.today_matches()`、`play_today_rankings()`は従来の委譲経路で新しいeventキーを受け取る。通常`play_today()`の進出校確定・完了判定へ追加順位戦は含めない。

## SQLite後方互換性

既存DBは以下のテーブルを持つ：

- `ranking_event_snapshots`：年度・大会・groupで1イベント
- `ranking_matches`：年度・大会・match_idで一意

SQLiteの既存PKを書き換えない。

- 新規`ranking_event_snapshots_v2`：`year,competition_id,group_id,ranking_instance_id`の複合PK
- `ranking_matches.ranking_instance_id`：既存DBは`ALTER TABLE ADD COLUMN ... DEFAULT ''`で自動移行。旧レコードは空欄を維持
- `BrowseRepository.save_ranking_sidecar`：保存した**同一イベント**の古いmatch_id行だけ正確に削除・差し替える。従来のgroup全削除は行わない
- `load_ranking_sidecar(year,competition_id,group_id,ranking_instance_id="")`：従来3引数は旧レコードを読み込む。4引数目指定で新しいインスタンスを読む
- `list_ranking_sidecars`：旧＋新スナップショットを日付順に返す
- 日付別・大会別の順位戦閲覧クエリでは旧レコードと新レコードを一緒に取得可能
- browse season再構築では旧・新の保存済みスナップショットを年度単位で削除し、以前の架空年度結果を混在させない

## 2026実証データへの接続

`build_verified_fmt025_2026_daily_sidecar()`が1日分だけ生成する点は維持しながら、日付由来の安定した`event_id`を付与する。静岡春季西部地区の4月4日・11日イベントを**両方同時に登録**できる。

実在の学校IDはPhase 1マスターに照合した53校のものを使い、資格確定済み学校集合`locked_school_ids`が揃ったときに限りsidecarを作成する。実際の対戦結果のスコアや勝者は架空ゲームへ自動移植しない。

## 残存項目

- 静岡秋`RR20260023`藤枝明誠（中部）対沼津東（東部）は跨地区。1地区の順位イベントに勝手に入れず、`review_cross_area_fixture`を維持
- 広島春秋は代表決定戦3件を`excluded_qualification_decider`として隔離。実際に出場権確定後の追加順位戦が存在するか再調査
- FMT022・FMT025の研究タスク`RS2026025`・`RS2026026`は、年次完全再現・GUI表示が終わるまで`design_pending`を維持
- 正式ゲームGUIへの専用UIは作成しない（read model基盤まで）

## 回帰テスト

`tests/test_stage13e3g5_multi_instance_ranking.py`に以下を追加。

- 同じ地区の4月4日と4月11日で試合IDが一意
- 同地区の2つのsidecarを同時に登録、別々に結果解決
- 複数イベントsnapshot／restoreで状態の保持
- 同一event_id重複、異常なイベントID、改ざんキー拒否
- 旧形式のID・snapshotの完全互換
- SQLite旧・新併存、日別読込、片方の保存が他方を削除しないこと
- event列が存在しない旧SQLite DBの無破壊migration
- 静岡跨地区と広島代表決定戦の隔離を維持

次工程は、静岡秋の跨地区カードの大会上の位置付けと、広島の代表確定後順位試合の有無を公式資料で追加確認する。これらが未確定の間は正式に「FMT025対応完了」としない。
