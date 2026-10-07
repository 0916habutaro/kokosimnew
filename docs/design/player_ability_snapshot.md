# PlayerAbilitySnapshot 設計 v1

作成日: 2026-10-07

## 目的

Stage 13AのPlayer本体から能力を分離し、ある時点の能力を再現可能なsnapshotとして保持する。

## 識別情報

- player_id
- school_id
- reference_year
- academic_year
- primary_position
- generation_seed

## Config provenance

能力snapshotにはseedだけでなく以下を保存する。

### Ability catalog
- catalog_config_id
- catalog_revision
- catalog_sha256

### Scale
- scale_config_id
- scale_revision
- scale_sha256

### Generation
- generation_config_id
- generation_revision
- generation_sha256

同じseedでもconfigが変われば生成結果が変わるため、完全再現にはconfig provenanceが必要。

## 全選手が持つ能力

投手を含む全選手が次を持つ。

- contact
- power
- plate_discipline
- strikeout_resistance
- bunt
- speed
- baserunning
- stealing
- arm_strength
- fielding
- throwing
- position_aptitude

高校野球では投手も打席に立つため、投手を投球専用モデルにしない。

## 捕手専用

primary_position=C の選手だけ:

- catching
- game_calling

その他の選手では null。

## 投手専用

primary_position=P の選手だけ:

- velocity_kmh
- control
- stamina
- stuff
- strikeout
- groundball
- composure
- pitch_repertoire

その他では null / empty。

## 守備位置適性

対象:

- P
- C
- 1B
- 2B
- 3B
- SS
- LF
- CF
- RF

主守備位置は高適性分布、その他はuntrained分布から生成する。

将来secondary positionモデルを追加するときは、untrained→secondaryの中間分布をconfig側へ追加する。

## 球種

投手は2〜4球種。

現行v1:
- four_seamを必須
- 残りを設定pitch_typesからseed選択
- 各球種にquality / command / usage
- usage合計=100

球種のquality / command / usageもnamespaceを分離する。

## RNG isolation

通常能力:

`player_ability_v1:{reference_year}:{player_id}:{ability_id}`

守備適性:

`player_ability_v1:{reference_year}:{player_id}:position:{position}`

球種:

`player_pitch_v1:{reference_year}:{player_id}:{pitch_type}:...`

能力Aの生成ロジックを変更しても能力Bまで不必要に変化しにくい。

## Snapshotは成績ではない

snapshotに以下を入れない。

- 打率
- 本塁打
- OPS
- 防御率
- 奪三振数
- 勝敗

これらはPlayerGameStats / SeasonStatsへ置く。

## Snapshotは状態でもない

以下も別モデル。

- fatigue
- condition
- injury_status

能力snapshotを疲労で直接書き換えない。


## Stage 13B-4 school-aware生成

Stage 13B-2の `PlayerAbilityGenerator` はbaselineとして維持する。

通常のゲーム生成では `SchoolAwarePlayerAbilityGenerator` がbaseline snapshotへ `SchoolIntakeProfile` を適用し、`IntakeAdjustedPlayerAbilitySnapshot` を生成する。

追加provenance:

- intake_config_id
- intake_config_revision
- intake_config_sha256
- intake_program_quality_z
- intake_cohort_quality_z
- intake_quality_z

学校差はこの選手snapshotの時点で表現し、TeamStrengthへ固定bonusを後付けしない。
