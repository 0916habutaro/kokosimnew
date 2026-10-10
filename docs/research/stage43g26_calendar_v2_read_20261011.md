# Stage 43G-26：架空ゲームカレンダーv2からA方式原本を日付別閲覧する互換read model

作成日：2026-10-11。Stage43G-25 PR #166 はCI全件成功を確認しmainへマージ済み（`266527dfd94b17d9440cf43f0a87a1803fa206e7`）。

## 目的と設計境界

これまでの`CareerCalendarV2Archive`は「ゲーム年度別の明示登録済み架空ゲーム日程」と、従来A方式原本の`YYYY-MM-DD`が一致するかの全件検証までできるが、**ゲーム画面で日付を指定して当該日の結果を見る**ための互換read modelはなかった。

Stage43G-26は`phase2_engine/career_calendar_v2_read_model.py`の`CareerCalendarV2MatchReadModel`として実装し、前年度の試合原本やゲームセーブのスキーマを一切書き換えず、v2日付を日別・年度別表示の「検索キー」として扱う。

## 画面に返す読み取りデータ

- `year_dates(game_year)`：年度の明示許可済み大会日程を`GameDaySlot`順で並べ、日付別に大会ID一覧、**保存済み試合数**、西暦9999以下のみのISO日付を返す。まだ試合のない予定日も0件として表示。日付の時系列以外に大会順位・勝者・シード権は推定しない。
- `date_page(day_token,competition_id=None,limit=50,offset=0)`：ゲーム論理日`G2026:04-01`から旧原本ISOを照合、年度／大会IDで絞った試合一覧（高校ID・得点・試合ID・原本SHA）を返す。1～100件ページング、総試合数を付加。**元の試合日を改変したり、架空ゲーム日程を公式日付と称したりしない**。
- いずれも年度内の保存済み試合をSQLiteの`mode=ro`で読み、**ページ外を含む元試合JSONのSHA・主キー・試合日・参加学校ID・得点の原本同一性、当年度の架空v2カレンダーに登録済みであることを全件検証**してから結果を返す。日程未登録、保存済み日付が予定外、原本ハッシュ変更、主キー／原本内容不一致はfail-closedで拒否。
- この実装はページングした表示件数を抑えるが、整合性のため**指定年度の元試合全件を走査・検証**する。数十万試合/年度の将来規模では別途、原本SHAに紐付く不変の読み取り索引を設計する必要がある。速度が一定とは主張しない。
- 現在の閲覧モデル`CareerHistoryBrowseModel`に`fictional_calendar_year`／`fictional_calendar_day`としてオプトインで接続。既存`HistoryRoute`や通常の学校／大会／試合／選手閲覧を変更しない。新しい正式Tk GUI画面への登録は後工程。
- CLIは明示したユーザーセーブの`historical_matches.sqlite3`・`sandbox_calendar_v2.sqlite3`を**一切更新せずに**`--year`または`--day-token`で結果を表示。例：

```sh
python -m phase2_engine.career_calendar_v2_read_model --slot-root SAVE --year 2027

python -m phase2_engine.career_calendar_v2_read_model --slot-root SAVE --day-token G2027:04-01 --competition-id CMP000086 --limit 30 --offset 0
```

v2サンドボックス計画が未作成の古い実セーブについては**閲覧用v2日付を捏造せず**、計画が存在しないというエラーを返す。従来の学校／年別read modelはそのまま利用できる。

## 10000年度以降の分離

- `CareerCalendarV2Archive`には`G10000:02-29`などの承認済み架空計画を保存・閲覧できる。ただし`gregorian_iso_date=None`であり、`post_9999_gameplay_supported=false`。
- 従来のA方式`historical_matches.match_date`のまま10000年度の試合を書こうとしても、読取時には**通常の旧ISO日付ではないため拒否**する。独自トークンを従来の日付欄へ無断移行しない。
- 旧原本の日付別／大会別検索と完全なv2年月日での試合結果保存・GUI表示の切替、および全国大会を毎年新規実行する完全runtimeは未実装。今後正式なv2マッチ記録側に型付き日付フィールドを持たせる移行工程が必要。

## 回帰テスト・CI

`tests/test_stage43g26_calendar_v2_read_model.py`：
1. 2026の同日2試合・翌日0試合の年／日別表示、ページング・大会フィルタ
2. `CareerHistoryBrowseModel`経由のv2日付閲覧
3. 未登録日／大会・不正ページ指定の拒否
4. 原本SHA改ざん・SQLカラムとJSON不一致・計画SHA改ざんの拒否、読み取り前後SHA-256不変
5. 10000年の計画のみ表示・旧非ISO日付で保存しようとする原本は拒否
6. **2校×5年度（2026–2030）**合成のA方式原本15試合・年度ロスター10件・学校年度キャッシュ10件とv2日付表示の一致

`.github/workflows/career-calendar-v2-read.yml`に専用CI追加。既存のフルA方式・20/50年容量CIも引き続き実行される。mainマージは全Python単体テスト、関東17校E2E、専用v2日別閲覧CIの成功後とする。検証JSONはGitHub Actions artifactに30日保存。

## 次の工程

Stage43G-27候補：v2日付の専用永続化を実試合原本にも対応させる**互換版のセーブ契約**（旧A方式原本は改ざんせず読めること、新原本にもイニング別・個人成績・学校/選手IDの一貫性を保つ）、本番スケジューラの「大会ごとの開催日ルール」ゲーム化、正式GUIの日付別トーナメント閲覧。年数無制限は未完了で、全国3,000校×100年の実ゲーム運用性能も未検証。
