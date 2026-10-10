# Stage 43B：A方式のイニング別得点の確定・SQLite保存

作成日：2026-10-10
対象：`kokosimnew`、Stage 43A / PR #130を継承
方針：[historical_match_retention_option_a.md](../design/historical_match_retention_option_a.md)

## 1. 今回の実装範囲

A方式のうち、以前は保存できなかった **A-2「イニング別得点」** を、能力ベース試合シミュレーションの確定結果からSQLiteまで接続する。

- `game_core.match_contract.InningScore` を新設：`inning`, `half`, `batting_team_id`, `was_played`, `runs`。
- `MatchSimulationResult.inning_scores` を追加：試合生成時には全半イニングを確定出力。既存の外部callerや旧データは `None`（未記録）として許容し、架空の得点配分を生成しない。
- `MatchSimulator` で各半イニングの開始前後の得点差を記録。最終回表終了時に後攻校がリードしていれば、裏は `was_played=False`, `runs=None`。
- `validate_match_simulation_result`：半イニング順序・得点合計と最終スコアの一致・打席イベントとの整合・未実施の扱いを検証する。
- `BrowseRepository` のスキーマをv4に更新し、`match_inning_scores` テーブルを追加。複合試合キーと半イニングキーで一意保存。既存DBへ追加するだけで旧年度行の削除・架空バックフィルは行わない。
- `replace_season_match_results()` の再保存／置換対象に追加し、`inning_scores_for_match(year, competition_id, match_id)` で半イニング順に閲覧可能。

## 2. 保存契約と欠損ルール

```text
試合シミュレーション：MatchEvent（内部計算）
       ↓ その場で得点を確定
MatchSimulationResult
  ├─ team1_score / team2_score
  ├─ inning_scores  ← 永続保存するA-2正本
  ├─ team_stats
  ├─ batter_stats
  └─ pitcher_stats
       ↓
SQLite ability_matches + match_inning_scores + 各GameStats
       ↓
BrowseRepository.inning_scores_for_match()
```

- 半イニング実施済み0点：`was_played=1, runs=0`
- 最終回裏を実施せず試合終了：`was_played=0, runs=NULL`
- イニング情報が存在しない旧方式：`inning_scores=None` またはSQLite対象レコード0行（「未記録」）。0点として扱わない。
- 生成結果の表・裏の合計は必ず最終スコアへ一致。違えばエラーとして保存しない。
- 既存スキーマに詳細GameStatsがない `generated_v1` 等のスコアは依然としてイニング内訳が未記録。**スコアだけからの推定配分は行わない**。
- `match_events` テーブルは現時点で維持。今回のA方式試験は新規結果のイベントリストを空にしてSQLiteへ保存してもスコアボード・個人成績を復元できることを確認する。永続化省略を正式設定化する工程は別途対応。

## 3. 既存機能への影響

- 旧`MatchSimulationResult` 生成側・他テストへの互換性を保つため、`inning_scores` は末尾の任意フィールドとし、`None` は過去結果の欠損状態とする。
- `SCHEMA_VERSION` を3→4へ変更し、通常の`CREATE TABLE IF NOT EXISTS`による追加スキーマを利用。既存の試合／年度は削除しない。
- `replace_season_match_results` は従来通り**同一年度を置換するAPI**。確定年度を保護する設計は後続のStage 43C課題。
- 正式GUIの専用スコアボード画面は未実装。今回は読取APIまで。
- 2026広島秋西の公式番号25件／敗者矢印32件／春秋8地区48件は引き続き公式未確認で、本変更により本番FMT025等を有効化しない。

## 4. 試験

`tests/test_stage43b_inning_score_persistence.py`

- シミュレーション結果で全半イニング順序・合計得点・打席イベントとの整合が成立。
- 9回裏の未実施と、実施した0点を区別。
- 1試合の打席イベントをSQLiteに保存しなくても、イニング別得点と打者／投手のGameStatsが読み出せる。
- 旧形式（イニング別得点欠損）を保存しても架空のイニング得点を生成しない。
- 得点合計不一致時は保存を拒否し、既存データが破壊されない。
- 順序違反、選手／チームID違反を検出。
- v3相当のDBに新テーブルを追加しても旧年度レコードを保持。

## 5. 次工程

1. **Stage 43C**：live runtimeの試合確定→履歴SQLiteへの追記・重複防止・復元の整合。
2. 同一年度replaceのガードと、次年度への確定記録引き継ぎ。
3. 正式GUIにA方式スコアボードと試合別個人成績を接続。
4. optionalな `match_events` 永続化の運用設定化、履歴なしでも表示できる自動テスト。
5. 100・500・1000年相当の履歴DB性能・復元試験。

本Stage単独で「全大会の全試合のA方式が完全保存済み」「年数無制限進行が完成」とは宣言しない。
