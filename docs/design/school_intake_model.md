# School Intake Model 設計 v1

作成日: 2026-10-07

## 目的

学校masterへ固定の戦力値を保存せず、各年度に入学する架空選手の母集団差を通して学校間の戦力差を作る。

処理順は次のとおり。

```
school_id + entry_year + seed
  -> SchoolIntakeProfile
  -> PlayerAbilitySnapshot の生成値を調整
  -> StartingLineup / PitchingStaff
  -> TeamStrengthSnapshot
```

TeamStrengthへ学校補正値を直接加算しない。

## 重要な意味

`school_intake_v1` は実在校の実力評価ではない。

- 実在校名や所在地を使っていても、program_quality_z は架空選手生成用の合成潜在値
- 現時点で過去大会成績・進学実績・スカウト評価等とは接続しない
- 「この実在校は強い／弱い」という事実を表す値ではない
- 将来実データで校正する場合は別工程とし、根拠・期間・更新ルールを文書化する

## 2階層の入部品質

### program component

学校単位で持続する合成成分。

namespace:

`school_intake_v1:program:{school_id}`

同一seed・同一school_idであれば、入学年度が変わっても同じ値になる。

### cohort component

入学年度ごとに変化する成分。

namespace:

`school_intake_v1:cohort:{school_id}:{entry_year}`

同じ学校でも2024年度入学と2025年度入学では異なる。

### 合成

初期値:

```
intake_quality_z
  = 0.8 * program_quality_z
  + 0.6 * cohort_quality_z
```

0.8² + 0.6² = 1.0 とし、独立成分を合成したときの分散が極端に膨らまないようにする。

最終値は -2.5〜+2.5 にclipする。

## 選手能力への適用

Stage 13B-2の `PlayerAbilityGenerator` はbaselineとして残す。

通常のゲーム生成では `SchoolAwarePlayerAbilityGenerator` を使用し、baseline能力生成後に `intake_quality_z` に応じて能力を調整する。

対象:

- batter scalar abilities
- catcher-only abilities
- pitcher abilities
- 主守備位置のposition aptitude
- pitch quality
- pitch command

pitch count、pitch type、usageはStage 13B-4では変更しない。

これにより「強い学校だから最終TeamStrengthに+10」ではなく、「質の高い入部層が複数学年に存在し、結果としてスタメン・控え・投手陣が強くなる」という経路になる。

## provenance

School-aware能力snapshotには以下を追加する。

- intake_config_id
- intake_config_revision
- intake_config_sha256
- intake_program_quality_z
- intake_cohort_quality_z
- intake_quality_z

TeamStrengthSnapshotには以下を追加する。

- school_intake_config_id
- school_intake_config_revision
- school_intake_config_sha256

## baseline比較

調整値の妥当性確認では、同じschool_id・seed・選手構成について

- baseline: PlayerAbilityGenerator
- intake: SchoolAwarePlayerAbilityGenerator

を比較する。

見るべきものは主に学校間分散であり、全体平均を大きく押し上げたり押し下げたりしないことを確認する。

## 変更しやすさ

数値は `config/abilities/school_intake_v1.json` に置く。

Python側へ学校ランクや能力補正値を直書きしない。

数値調整はrevisionを上げ、変更前→問題→変更→変更後→判断を `docs/tuning/` に残す。
