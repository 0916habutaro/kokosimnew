# Stage 13E-3G-34：FMT025段階再生を大会・試合日・学校のread modelへ変換

実施日：2026-10-10

## 設計の結論

Stage33で `waiting`（前の試合待ち）、`ready`（対戦校確定、結果は未公開）、`completed`（既登録結果を公開）を表現できるようになった。しかし、Stage12Q/12Rで用意した `DatedMatchRow` とSQLite `matches_by_date` は、原則としてスコア・勝者・試合日が確定した**完了済み試合の結果閲覧**を前提としている。未実施予選を既存テーブルに強制INSERTすると「得点なしの結果」「公式日がないのに日付がある」「不明の出場校が実在する」などの誤認を招く。

そこでStage34では **SQLite構造を変更せず、GUIへ後から組み込める補助read model** を追加した。試合予定・成績・公式日付を新規生成せず、Stage33の内部進行状況を読み取り専用で表示する。

## APIと4種類の出力

`phase2_engine/hiroshima_fmt025_preview_browse_model.py`

`build_fmt025_preview_browse_views(payload, checkpoint, data_dir=None)` は入力をStage32契約・Stage33チェックポイントへ必ず再審査し、以下をイミュータブルな`QualifierBrowseViews`として返す。

| 出力 | 主要項目 | 未確定時の取り扱い |
|---|---|---|
| `matches_by_date`（試合一覧） | 試合ID、フェーズ、`match_status`、校名、出典別試合日、得点・勝者・敗者 | `waiting`は両校空欄、`ready`は両校のみ。未完了は勝敗空欄。得点は完了済みも`None` |
| `competition_results`（大会別進行） | 試合総数、完了・ready・waiting数、参加校数、代表枠数・確定数・残枠 | 優勝・準優勝など未証明の概念は出力しない |
| `school_records`（学校別） | 閲覧時点までの試合数・勝敗数・readyの件数・出場記録・代表権状態 | 現時点で学校が未判明の待機試合を、特定校の「次の試合」と推定しない |
| `confirmed_berths`（代表校） | 代表校、県大会出場資格の由来、資格が確定した試合ID | **単なる勝利**では代表権を付与せず、実際の明示`winner_awards_berth`の試合結果に限定 |

検索補助：`matches_for_date(date)`、`matches_for_school(school_id)`、`matches_for_competition(competition_id)`。GUIやSQLite repositoryに組み込む前段階で、別プロセスのCLI・ヘッドレス試験から利用できる。

## 日付・得点・学校IDの真偽

- 架空4校の試験：日付は全件`""`、`date_source=undated_preview`。特定の日に開催されたという主張をしない。
- 2026年秋季広島西部のStage25の史実：**完了として公開した試合に限り**、二次結果から記録済みの日付を`match_date`、`date_source=secondary_dated_result_only`として公開。未実施状態の結果日付は公開せず、公式球場・対戦カードの正式日程としない。
- 得点：Stage33の元情報は勝敗と接続が中心のため、全試合の `team1_score`／`team2_score` は `None`、`score_source=not_available` を維持。**得点を捏造しない**。
- 学校名：Stage25で記録された表示名または架空IDをそのまま使用。既存の`schools.csv`正式学校IDへの突合・名寄せを今回追加したわけではない。内部の表示上の学校IDもこの段階の文字列であり、学校マスターの恒久キーと混同しない。
- Stage24/27の公式画像大枠は先行成果だが、個別公式番号25件・敗者進行矢印32件は未確認のまま、`official_match_number=""`、`is_official_draw_verified=False`とする。

## 検証ケース

`data/research/2026/hiroshima_fmt025_browse_expected_states_stage13e3g34.csv` へ架空4校3試合の4段階期待状態を保存。

| 段階 | completed | ready | waiting | 代表枠確定 |
|---|---:|---:|---:|---:|
| 開始 | 0 | 2 | 1 | 0/3 |
| P1結果公開 | 1 | 1 | 1 | 1/3 |
| P2結果公開 | 2 | 1 | 0 | 2/3 |
| R1結果公開 | 3 | 0 | 0 | 3/3 |

2026秋季広島西部のStage25の二次結果を段階公開すると、最終的に**18校・25試合・7代表校**となり、学校別集計の総試合数50チーム出場、勝利数25・敗戦数25が成立する。これは閲覧モデル側の内部整合を検査したものであり、公式抽選の敗者移動を確定したものではない。

`tests/test_stage13e3g34_hiroshima_preview_browse_model.py` は、未来の出場校を見せないこと、未実施の勝者を見せないこと、架空日付・架空得点を記録しないこと、実際の代表確定試合IDに紐付くこと、校別試合・勝敗集計、年度の誤認、改ざん済みチェックポイントの再審査、既存SQLite/GUIクラスと別系統であることを確認する。

## 本番への接続状態と次の工程

既存の`BrowseRepository`、`DatedMatchRow`、`BrowseGuiModel`、Tkinter GUI、SQLiteの本番テーブル・試合結果保存は**変更していない**。本モジュールのread-onlyビューをGUIへ表示する場合には、既存のシミュレーション済み結果一覧とは別の「予選進行プレビュー」メニューとして、出典・未確定表示の凡例を常時併記するのが安全である。

Stage30の未確認48経路規則、秋西2026の個別公式試合番号25件・矢印32件、年度独立の敗者移動アルゴリズム、本番FMT025と任意順位戦は未解禁。Stage35での具体的な次工程は、読み取り専用GUIの一画面にこの補助ビューを**試験的に表示**し、DBの本来のスコア・学校ID等に混入しないことを実機で確認すること。ただし正式GUI構築の段階は別途判断。

**Stage34完了の定義：read-onlyの変換層、4段階の固定状態、18校25試合7代表の史実整合、未確定・出典区別を守る回帰テストの確立。**
