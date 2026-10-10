# Stage 43F-4：確定した前年大会結果から翌年度の出場資格を導く

作成日：2026-10-10  
前提：Stage 43F-3 / PR #137 main反映済、マージ後CI成功  
対象：ココシミュNewのゲーム生成試合。2026年の公式大会記録とは分離。

## 1. 背景・今回の解決範囲

Stage 43F-3で2027年の仮大会について10支部の予選→本戦を実際に進行できるようになった。これに対し、Stage43Fの`build_future_season_blueprint()`は、前年秋の順位を任意の`previous_results`JSONとして受け取るにとどまり、**当該ゲームセーブの確定試合から生成された値である保証がなかった**。

本Stageでは、既存の`HistoricalMatchArchive`（Stage43C）と年次封印（Stage43D）を利用し、保存済みの試合勝敗に一致する`CompetitionRun.outcome`だけを、次年度の参照資格として利用できるようにする。

**今回の正式な対象は前年秋の県大会の上位n校を参照する6ルール**：

| 出場規則 | 翌春大会ID | 元の秋県大会 | 選出方法 |
|---|---|---|---|
| ACR000004 | CMP000084 | CMP000085 | 上位4校 |
| ACR000005 | CMP000090 | 当該県の秋県大会 | 上位8校 |
| ACR000006 | CMP000092 | 当該県の秋県大会 | 上位8校 |
| ACR000010 | CMP000109 | 当該県の秋県大会 | 上位4校 |
| ACR000017 | CMP000133 | 当該県の秋県大会 | 上位8校 |
| ACR000020 | CMP000094 | 当該県の秋県大会 | 上位64校 |

上表の適用は、各年度の大会方式・規則が有効であるというゲーム用仮定に基づく。自動的に2027年の実際の公式出場資格が確認された、という意味ではない。

**ACR000015** の前年秋地区大会参加校を参照する条件 `participants_from_destination_prefecture` は、順位だけで自動判定しない。センバツの委員会選考なども引き続き未解決。

## 2. 実装

`phase2_engine/career_competition_outcomes.py`：

- `CareerCompetitionOutcomes.record_completed(run)`：
  - `CompetitionRun`の`outcome`・MAINの全対戦結果・優勝校・準優勝校・最終順位を検証。
  - 当該年度の`HistoricalMatchArchive.career_years`が**sealed**かつ全試合台帳SHA-256が一致することを必須化。
  - MAINで実際にプレイした全試合IDを履歴DBから読み、相手校・勝者・敗者・試合年度・ステージをすべて照合。結果欠損・結果改変・異年度混入・ラウンドの最終勝者と優勝校の不一致を拒否。
  - 保存元試合IDと行fingerprintのmanifest、年次台帳digestを大会順位スナップショットへ保存。
  - 同じ大会結果の再保存はスキップ。異なる順位を再登録した場合は不一致として拒否。勝敗のない旧方式の架空補完はしない。
- `CareerCompetitionOutcomes.previous_results(year)`：
  - sealedのゲーム内年次記録からのみ出場枠用`{year,status:"completed",source:"game_result",ranked_school_ids}`を返す。
  - 台帳が改変されていれば発行せずエラー。前年の試合データが保存されていても、大会全体の順位が確定していなければ何も発行しない。
- `build_future_blueprint_from_archive(data_root,year,base_seed,match_archive)`：
  - **対象年の前年度`year-1`を明示的に読む**。該当する封印済み結果だけをStage43Fの既存`build_future_season_blueprint`に渡す。
  - `previous_results_source="sealed_career_game_archive"`で参照元を表示する。
  - 全162大会の仮日程、委員会選考`pending`、`live_runtime_ready=False`の扱いは維持。

保存先は試合と同じ`<save_root>/<slot_id>/historical_matches.sqlite3`内の`historical_competition_outcomes`テーブル。既存の年次台帳・試合データを削除・書換しない。

## 3. データフロー

```text
2026年秋の大会を実際に完了（CompetitionRun）
            +
2026の試合がSQLiteへ永続化・年次封印済み
            ↓
MAIN全試合の勝敗とCompetitionRun.outcomeを突合
            ↓
historical_competition_outcomes に大会順位を追加保存
            ↓
build_future_blueprint_from_archive(year=2027)
            ↓
2026のゲーム内順位を6種の前年秋 top_n 規則へ接続
            ↓
2027年の仮大会ブループリント：
  対応可能な出場枠 → resolved（上位校IDのみ）
  不足の秋大会結果 → unresolved
  秋地区大会の参加資格 → unresolved
  センバツ選考 → pending
```

**これはゲーム内出場資格の算出まで**。対象県の2027年度春大会を実際に起動し、除外・代表枠・シード組合せを処理するための`AnnualCompetitionInput`への最終接続は別工程（Stage43F-5以降）。

## 4. 受入テスト

`tests/test_stage43f4_verified_previous_year_results.py`で16件を追加：

1. ゲーム内の2026秋県大会4校・本戦3試合を保存、年度封印、`CompetitionRun`照合で2027春の上位4校枠へ接続。
2. 同一記録の冪等再保存、DBを再オープンしての順位再読込。
3. 未封印年度・MAIN試合欠損・勝敗食い違いの拒否。
4. 結果を変更した順位・優勝校・試合勝者の拒否。
5. 封印後の試合台帳SHA-256改変、順位payload改変を検知。
6. 大会結果が確定していなければ前年秋枠を未解決で維持。
7. 他県の前年枠と地区秋・センバツは独立して未解決扱いを維持。
8. 2028の資格に2026年度の結果を誤利用しない。
9. 履歴DBが未作成の場合はread-only検査で勝手に新DBを作らない。

## 5. 制限・次工程

- 現段階のゲーム内2026年シーズンには、実行できない予選・日付不足の大会が残りうる。**年次封印まで完了できなければ、前年度の結果を資格用正本として自動発行しない**。
- `historical_competition_outcomes`は試合完了後に、終了年度の`CompetitionRun`を明示的に登録するAPI。現在の`LiveGameService.finalize_season`に自動的な一括大会結果登録を統合したわけではない。
- 3位決定戦がなく同順位となる場合には、既存大会エンジンの順位契約を引き継ぐ。上位nの境界に同順位がある場合の選抜ポリシーは別途仕様が必要。
- `top_n`の規則だけを処理。地区大会の代表/参加校、秋県大会→秋地区大会、前年夏優勝から秋県大会の直接出場枠、センバツの委員会選考等はまだ未対応。
- 2027全国162大会の出場校生成・試合日修正・大会内接続、選手成長／実ゲーム本編の年度切替・正式GUIは未実装。
- 2026年広島地区予選の未確認経路は本実装で解禁しない。学校ID・年度・大会IDと生成済みゲーム内結果を使用し、実世界の史実記録と混合しない。
- 将来は年次確定フローに大会の`CompetitionRun`全件保存・検証を追加し、**前年結果→翌年度資格→年度プレイ→履歴保存**のEnd-to-End試験に進む。

### 実装例

```python
from phase2_engine.historical_match_archive import HistoricalMatchArchive
from phase2_engine.career_competition_outcomes import (
    CareerCompetitionOutcomes,
    build_future_blueprint_from_archive,
)
history = HistoricalMatchArchive("out/saves/career/historical_matches.sqlite3")
# 年度内試合を保存し、正常に終了・封印した後：
outcomes = CareerCompetitionOutcomes(history)
outcomes.record_completed(completed_run) # 出場校・大会・勝敗の整合を検証
blueprint = build_future_blueprint_from_archive(
    "data", year=2027, base_seed=1001, match_archive=history
)
```
