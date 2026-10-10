# Stage 43A：A方式の過去試合記録・保存充足監査

策定日：2026-10-10
対象：kokosimnew main（PR #129のA方式方針反映後）
区分：既存コード／DB正本監査＋読取専用SQLiteデータ充足診断の初版
参照：[historical_match_retention_option_a.md](../design/historical_match_retention_option_a.md)

## 1. 確定した前提

- **A方式を採用**：全確定公式戦について最終スコアとイニング別得点、試合別個人成績を後年も閲覧する。打席ごとのイベント列は歴史保存の必須情報にはしない。
- **無制限年度進行は目標**：100/500/1000年は負荷検証点であって上限ではない。しかし現在の一括seasonと日付進行は2026年／年末に制約がある。
- 史実・研究用の二次結果とゲーム内生成結果は混同しない。欠損データを0や推測値で埋めない。
- 本監査は現在のmainの構造に関するもの。**実運用DB全年度の内容監査やA方式の実装完了を意味しない**。

## 2. A方式の実装状態と根拠

| 保存要素 | 関係コード・テーブル | コード監査結果 | 次工程 |
|---|---|---|---|
| A-1 大会・試合・スコア・対戦校 | `phase2_engine/browse_views.py` DatedMatchRow、`browse_repository.py` matches_by_date | **基本的な永続化あり**。日付出典とscore_sourceあり。ただし一部は実際の日付でなく projected_v1 や未定 | 完了／bye／未実施の状態判定、全国pre-MAINを含む全公式戦の出力漏れ監査 |
| A-2 イニング別得点 | `game_core/match_simulator.py`、MatchSimulationResult、browse SQLite | **不足**。MatchSimulationResultにlast_inning/ending_halfはあるが半イニング別得点を独立して保存するフィールド・テーブルがない。試合生成内部では inning/half/runs_scoredを持つMatchEventがある | イニング得点の確定正本、未実施の裏と0点の区別、延長・サヨナラ・コールド整合の設計／実装 |
| A-3 チーム安打・失策等 | MatchSimulationResult.team_stats、team_game_stats | **基盤あり**。生成された能力モデル試合で保存できるが、generated_v1や研究資料など全試合への保証はない | 出典別・対象大会別の欠損とスコア整合監査 |
| A-4 打撃・投手の試合別個人成績 | MatchSimulationResult.batter_stats/pitcher_stats、batter_game_stats/pitcher_game_stats | **基盤あり**。年/大会/試合/選手IDを正本として保存。全試合・年度横断の同一人物保証は別問題 | A方式単独の歴史read modelとPlayer IDの翌年継続、試合単位の存在・件数監査 |
| 任意：打席イベント列 | `match_events` と `events_for_match()` | **現在は全イベントをSQLiteへ永続化**。A方式を採用しても直ちに削除すると既存試験・利用者が壊れる | 将来の新規生成結果で永続化ON/OFFを選べるようにし、既存値は保存 |
| 長期・年度跨ぎ | browse_seasons(year)／各テーブルyear複合キー | **複数年度の保持は構造上可能**。同一年度のreplace_season_views等はdeleteして再作成するため保護要 | 追記・確定年度の保護・明示的再構築の契約 |
| ゲームセーブと履歴SQLite | `phase2_engine/live_season_save.py`、live_game_service、browse_repository | **別経路**。Live saveにはcompleted_match_resultsがあるが全てのA記録をSQLiteに確定保存する一貫した出口は未確認 | completed-match→履歴DBの不可分確定保存、リカバリと重複投入テスト |

## 3. 実装上の注意

### 3.1 「最終スコア」からイニング別得点は分からない

MatchSimulatorには `team_runs` の合計値と `MatchEvent` の各打席の `inning / half / runs_scored` が存在する。一方、MatchSimulationResultには確定した半イニングの合計値を保持していない。**結果モデル→SQLiteへ半イニング別の正本を追加してから打席イベント保存を任意化する**必要がある。

- 表・裏の得点は半イニング実施の有無と区別する。
- 表を終えて裏を実施せず終了した場合、裏は「未実施」であり「0点」ではない。
- 全打席のイベント列がなくてもイニング別スコアを永続参照できる構造にする。
- リザルトの出典が generated_v1 等の簡易結果の場合、イニング・個人成績が未生成なら欠損として扱う。

### 3.2 個人成績は任意イベントの代用品ではない

BatterGameStats / PitcherGameStats の整数計数は通算成績に利用できる。しかし「何回に誰が何を打ったか」「決勝打の瞬間」を後から確定的に再現するための履歴ではない。A方式ではそれを表示保証しない。

### 3.3 同一年度再生成の注意

`BrowseRepository.replace_season_views()` は既存 `browse_seasons` の同一年を削除し再登録する。外部キー連鎖と後続replace系の実装があるため、無期限の歴史保存では「次年度の保存」と「旧年度の明示的上書き」は異なる操作としてガードする必要がある。

### 3.4 日付・出典

2026年の公式試合日程と、投影された日付（projected_v1）、研究用二次結果は混ぜない。未知のデータは unknown / 記録なしを表示し、必ずscore_source/date_source等の来歴を維持する。

## 4. 新規の読取専用診断ツール

```bash
python -m phase2_engine.historical_match_audit \
  --db out/kokosim_browse.sqlite3 \
  --year 2026
```

`--year` を省略すると DB にある各年度を順に監査。存在するSQLiteファイルに対して `mode=ro` で接続する。閲覧用 `BrowseRepository` のschema初期化DDLとは別にしており、診断時にDBを書き換えない。データが存在しなければ自動生成せずエラー。

出力（各年度）：
- 全試合行・bye・非bye・スコア保持済み・未確定／欠損スコア
- 同一試合で ability_matches、両校team_game_stats、打者stats、投手stats がそろう試合件数
- イニング別正本が存在し、得点合計を最終スコアと照合できる試合件数（現行テーブル未実装のため通常0）
- results scoreとability scoreの不一致件数（出典差異もあるため原因調査が必要）

**注意**：readiness件数は構造／行の存在を数える簡易監査であり、全項目の完全性や全大会の公式ルール、同じ試合でA-2とA-3/A-4が同時に存在することを証明しない。よって `full_a_claimed=false` 固定とし、完了認定は後続の正本検証で行う。存在しない `match_inning_scores` テーブルを作成したり書き込んだりしない。

## 5. 次の実装順序

| 優先 | 作業 | 完了条件 |
|---|---|---|
| P0-1 | イニング別得点を MatchSimulationResult に追加 | 各半イニングの実施有無・得点が一致し、従来の MatchEvent／seed再現に影響しない |
| P0-2 | SQLiteへの半イニング別得点の保存とread model | 1試合を閉じたあと打席イベントがなくてもスコアを閲覧できる |
| P0-3 | A方式のスコア・チーム・個人成績・イニングデータ整合監査 | 同一試合IDに対して総得点／学校ID／成績の欠損・不整合を検出する |
| P0-4 | live runtimeの確定試合→年度履歴DBを連動 | リロード・autosave・再処理で重複や消失が起こらない |
| P0-5 | 年度移行・終了年の改変保護 | 新年度の生成・保存で旧年度の試合情報を一切書き換えない |
| P1 | 打席イベント永続化の任意化／A専用読み出し | event 0件でもAの画面・集計が成立し、旧イベントレコードは維持する |
| P1 | 100/500/1000年相当の容量・負荷試験 | 上限設定ではなく長期安定性の検証とボトルネック改善 |

未検証：全47都道府県の予選進出経路、広島2026秋西の公式試合番号25件／敗者矢印32件／春秋8地区48件は引き続き未確認。正規大会エンジンへの反映を今回の作業で解除しない。

## 6. 検証方法

- `tests/test_stage43a_historical_match_audit.py` に、複数年度、bye/未確定、イニング得点一致/不一致、能力スコア差異、旧形式、SQLiteバイト不変の試験を追加。
- GUI実機の動作や全大会のデータ入力の検証を完了とはしない。
- 既存テスト全件をGitHub Actionsで確認し、新規コードの影響を監査する。
