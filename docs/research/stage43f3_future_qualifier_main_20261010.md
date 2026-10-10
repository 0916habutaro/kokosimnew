# Stage 43F-3：翌年度の支部予選→本戦を実際の大会エンジンへ接続

作成日：2026-10-10
対象：ココシミュNew
前工程：Stage 43F-2（PR #136、mainマージ・全件CI成功）
完成範囲：**2027年度のゲーム内試験大会における、FMT001支部予選からMAINへの勝ち上がり連結**。
本番の2027年全校所属・出場資格・全国162大会の自動進行・セーブは対象外。

## 1. 今回の対象と実装上の条件

最初に接続するのは、2026年方式が登録された **北海道秋季・支部予選→全道大会（CMP000013）**。支部予選には10支部のFMT001独立トーナメントがあり、決まった代表枠の学校をMAINへ送る。

- 2026年の地区所属テーブルを、そのまま2027年の所属だとすることはしない。**全グループの参加校を年次sandbox入力で明示**する。
- 予選代表は橋渡しモジュールが決めない。既存の `QualifierMainRuntimeState` が各グループ内の試合結果に基づいて代表を出力し、その結果をMAINへ渡す。
- 試合は `AbilityMatchResolver` とStage43Eの `CareerRosterArchive.roster(2027,school_id)` を使用。2027年度の選手を同一人物IDで扱い、A方式のイニング別得点・試合別打者／投手成績を生成する。
- 2026年の支部予選試合日を翌年度の月日に写像した仮日程を使用。ただし確認済み2027年公式日程ではなく、すべて `game_projection_v1` と記録する。
- 予選と本戦の両方の試合日があり、予選完了から本戦までの日付が逆転しないことを検証。
- 必要ラウンド数の見込みに満たない仮日付は起動前に拒否する。日付不足を適当に補完しない。

今回採用した形式は、独立したFMT001の2ステージ・`BRANCH_QUALIFIER→MAIN`であり、特殊方式や多段PRELIMINARYを含む県大会を**完了扱いにはしない**。

## 2. 入力と実行フロー

```text
build_future_season_blueprint()      ゲーム内2027仮大会
      +                                  + 
entrant_school_ids                  group_entrant_school_ids
全参加校を明示                    10支部すべてに明示割当
      +                                  +
CareerRosterArchive                 日付正本はゲーム内仮日程
全校2027年進級済みを検証           予選→本戦の順序を検証
                ↓
prepare_future_fmt001_qualifier_preview()
                ↓
AnnualCompetitionInput
  .year=2027
  .group_entrant_school_ids=明示sandboxマッピング
                ↓
TournamentEngine.prepare_scheduled_competition_runtime()
                ↓
QualifierMainRuntimeState
  支部ごとに実際の対戦を実行 → 代表校確定 → 全道MAIN起動
                ↓
FutureCompetitionPreview.play_next_date()
     継続Player IDのMatchSimulator + A方式個人成績
```

実行例：

```python
from phase2_engine.future_qualifier_bridge import prepare_future_fmt001_qualifier_preview

preview = prepare_future_fmt001_qualifier_preview(
    blueprint=blueprint_2027,
    competition_id="CMP000013",
    entrant_school_ids=sandbox_2027_entrant_school_ids,
    group_entrant_school_ids=sandbox_2027_groups_by_stage_group_id,
    roster_archive=saved_career_rosters,
    repo=repo,
    career_seed=career_seed_for_saved_rosters,
    ability_config_dir="config/abilities",
    match_config_dir="config/match",
)
# 決められた次の仮試合日だけを実行
first_day = preview.play_next_date()
# 予選完了後は、エンジン側がMAIN出場校を確定して次の日程へ進める
```

## 3. 入力保護

| 欠損・違反 | 挙動 |
|---|---|
| `official_calendar=true` や2026の正式出典混入 | 拒否 |
| 前年度所属を黙って利用する、1支部が未割当 | 拒否 |
| 県外校、未登録硬式学校、同一校の複数支部参加 | 拒否 |
| 予選人数が出場枠未満、予選枠総数がMAIN枠と不一致 | 拒否 |
| 予選必要ラウンド数・MAIN必要ラウンド数分の日付不足 | 拒否 |
| 予選日と本戦日が逆転 | 拒否 |
| 対象校の2027進級済み保存ロスターなし、seed不一致 | 拒否 |
| 同年夏優勝校などの外部直接出場資格の規則 | 未解決のため拒否 |
| 混合モデル・FMT025等の他方式 | このアダプタでは拒否 |

**未確認の広島2026秋西の進出・代表経路を、本番へ有効化することはない。**

## 4. 回帰テスト

`tests/test_stage43f3_future_qualifier_bridge.py` の13テストで：

- 北海道秋の10支部、出場枠20の構造を参照し、ゲーム用に40校を明示割当。
- Stage43Eの2026初年度ロスター→2027年度ロスターを各校で生成・SQLite保存。
- 全グループFMT001の支部予選を実際に試合生成し、代表20校が確定することを検証。
- 勝ち上がった20校だけでMAINトーナメントを実際に進行、全39試合（支部20＋MAIN19）の確定と優勝校を検証。
- 代表の所属、過去と同じplayer_id、イニング別得点、打者成績、年度・試合日、seed再現を検証。
- 未割当・重複・県外・未登録・日付不足・ロスター欠損・2026公式日程混同を拒否。
- 外部資格が存在する北海道春の別大会は、資格未解決として拒否。

## 5. 次工程

1. **Stage43F-4**：前年秋や夏の実際の保存済み試合結果から資格を導くゲート（地区大会・シード・直接出場も含む）。学校名ではなく学校ID、年度・大会ID・順位／優勝の確定を利用。
2. 地区予選の各方式FMT001～FMT026の年間適用と、学校・合同チームのゲーム内年度所属を定義。2026の方式を翌年度に使う際の未確認部分は保留。
3. 2027年度の全県大会・地区大会・夏代表選考の出場校を、任意入力ではなく**同一年の競技結果**から確定する。
4. **Stage43G**：セーブ枠に未来年度大会・全校選手・年度間資格とA方式過去記録を結合。ゲームが実際に2026→2027へ移行できるようにする。
5. 100年・500年・1000年の長期再現性、SQLite容量・read modelの性能を評価。

**Stage43F-3はsandboxで「予選から本戦へ試合を進められる」段階。2027年度の実世界の公式大会情報を登録・確認したわけではなく、全国すべての大会を自動生成したとも主張しない。**
