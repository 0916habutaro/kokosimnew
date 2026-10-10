# Stage 43F-2：翌年度の仮大会を実大会エンジンへ接続（限定sandbox）

作成日：2026-10-10
依存：Stage 43F / PR #135、Stage 43E / PR #134
対象：ゲーム内2027年度以降の**明示的に参加校が揃った、MAIN単独方式の大会のみ**
達成区分：**大会エンジン接続の第一段階**。全162大会・年度跨ぎの本編プレイ完成ではない。

## 1. ねらいと境界

Stage43Fでは全162大会分の`game_projection_v1`仮日程と大会マスターを作成したが、まだ試合を実際に動かす既存エンジンへ渡していなかった。Stage43Eでは在学選手を永久player_idのまま進級させたが、2027年度の大会開始と紐づいていなかった。

今回`phase2_engine.future_competition_bridge.prepare_future_direct_main_preview()`で、次の既存コンポーネントを**本物の試合生成・日付進行**へ接続する。

```text
2027年度ゲーム内仮大会・仮日程（Stage43F）
         +
外部から明示した出場校ID 32校など（公式認定を意味しない）
         +
CareerRosterArchiveの2027年度ロスター（Stage43E）
         ↓ 入力検証
AnnualCompetitionInput（year=2027、コンペ別seed）
         ↓
TournamentEngine.prepare_scheduled_competition_runtime()
         ↓
ScheduledCompetitionRuntime（日付ごとの試合）
         ↓
AbilityMatchResolver(roster_provider=CareerRosterArchive.roster)
         ↓
MatchSimulator：2027年度の継続選手IDで試合を進行、A方式GameStatsを生成
```

このアダプタは**sandbox_manual_v1**の明示的試験用出場校しか受け付けない。実際の2027年度出場校、委員会選考結果や夏の各地区代表を確定したという意味ではない。2026年度の実在日程・会場・名称を2027の事実として扱うこともない。

## 2. 実装内容

| 対象 | 対応 |
|---|---|
| `phase2_engine/future_competition_bridge.py` | 仮大会ブループリント+明示出場校+継続ロスターSQLite→従来の大会エンジンへ渡す。専用結果`FutureCompetitionPreview`と`play_next_date()` |
| `phase2_engine/competition_schedule_runtime.py` | `game_projection_v1`の予定日を割り当てた試合が、通常の`runtime_wave_v1`ではなく`game_projection_v1`をdate_sourceとして保持。2026通常の既存日付表示には影響しない |
| `tests/test_stage43f2_future_competition_bridge.py` | 32校の明示出場による2027年選抜型sandbox MAIN、試合の日付別実行、GameStatsと継続選手ID、seed再現、異常入力・公式出典誤用の拒否 |

## 3. fail-closed（未確認要素は進行しない）

- `blueprint.year>2026`／`source_structure_year=2026`／`official_calendar=false`／`provenance=game_projection_v1` を検証。
- `calendar_status=provisional_game_schedule`, `real_world_verified=false` の仮日程のみ受け付ける。
- 出場校は既存硬式学校IDを全件明示し、重複なし。対象大会MAINステージの想定チーム数が未達／過剰なら拒否。
- 現時点では大会ステージが**MAIN単独**であることが必須。pre-MAINの代表校が未確定のまま本戦に入れないようにする。
- 参加する全校に`CareerRosterArchive.roster(year,school_id)`の継続ロスターが既にあり、`cohort_policy=career_v1`、同じ`career_seed`、対象年度・学校が一致する場合のみ試合開始。
- 欠けた2027年ロスターを2027年乱数seedで最初から作り直すことはしない。
- 同一seed・同一出場校で大会の組み合わせを再現可能。出場校リストは生成済みでなく**明示入力**なので実際の選出事実を偽装しない。
- 2027の大会表示名は「ゲーム内2027年度…（仮大会）」であり、2026年度の実在の正式大会名を転記しない。
- 委員会選考が必要な大会は、本番選考ロジックが完成するまでは`sandbox_manual_v1`としてのみ進められる。
- 出場資格依存の未解決大会については、試合の自動参加校選出や本編進行を行わない。

## 4. 実際のプレビュー使用例

```python
from phase2_engine.repository import DataRepository
from phase2_engine.career_roster_archive import CareerRosterArchive
from phase2_engine.future_season_blueprint import build_future_season_blueprint
from phase2_engine.future_competition_bridge import prepare_future_direct_main_preview

repo = DataRepository("data")
rosters = CareerRosterArchive("out/slot/career_rosters.sqlite3")
preview = prepare_future_direct_main_preview(
    blueprint=build_future_season_blueprint("data", year=2027, base_seed=123),
    competition_id="CMP000001",
    entrant_school_ids=explicitly_selected_32_hardball_school_ids,
    roster_archive=rosters,
    repo=repo,
    career_seed=career_seed_used_for_all_saved_school_rosters,
    ability_config_dir="config/abilities",
    match_config_dir="config/match",
)
snapshot = preview.snapshot()       # 非公式・保存不可を明示
first_day = preview.play_next_date() # 最初の仮試合日で実試合を生成
```

※`explicitly_selected_32_hardball_school_ids`は利用側が明示的に設定する。既存の2026選抜出場校や学校一覧の先頭32校を実際の2027年代表と見なすものではない。年度継続ロスターも自動生成しないため、対象校の`2026→2027`保存が先に必要。

## 5. 保護事項と後続工程

- 今回のプレビューには**セーブと履歴SQLiteへのコミットを接続しない**。試合が動くことと、履歴として年度保存できることを区別する。
- `LiveGameService.new_game()`の2027年度全162大会自動起動は未実装。
- 2027の他大会への代表・ランキング伝播や前年秋の県大会成績を資格として引き継ぐ本番処理も未実装。Stage43Fの限定的な`previous_results`解決はブループリント上の情報にとどまる。
- 次工程は**前後の大会結果を読み取って進出資格を確定するゲートと、県／地区予選の年次学校所属・組合せ生成**。安全に動く範囲を広げる。
- 学校マスターの年次休廃部・合同チーム、地区再編成、部員全体規模、能力成長と新入生の総数配分は別設計が必要。
- 無制限年度構想には`datetime.date`の西暦9999年上限を越える日付表現が必要。今回の仮日程は2027～9999年のみ。
- 広島2026秋西の未確認番号・進出ルールを勝手に本番解禁しない。

今回の受入条件は「**実際の大会エンジンが、継続選手IDを使って2027年の仮日付に試合を生成すること**」であり、「全国全大会を2027年へ進められること」ではない。
