# Stage 13B-1 能力設計・変更管理基盤

作成日: 2026-10-07

## 目的

Stage 13AでPlayerと学校ロスターができたため、能力生成へ入る前に「後から安全に修正できる能力設計」を正本化する。

今回のStageでは能力値そのものの生成は行わない。

## 正本の分離

### 人間向け設計
`docs/design/`

- player_ability_design.md
- player_ability_catalog.md
- team_strength_design.md
- ability_tuning_workflow.md

### 設計判断
`docs/adr/`

- ADR-001 学校能力は選手から算出
- ADR-002 通常能力1〜100
- ADR-003 Player/Ability/Condition/Stats分離
- ADR-004 version付きRNG namespace
- ADR-005 調整値はconfigへ置く

### 機械可読設定
`config/abilities/`

- ability_catalog_v1.json
- ability_scale_v1.json
- player_generation_v1.json
- team_strength_v1.json

### 調整履歴
`docs/tuning/`

変更前・理由・変更・変更後・判断を残す。

## Ability catalog

v1で22能力を定義した。

打撃:
- contact
- power
- plate_discipline
- strikeout_resistance
- bunt

走塁:
- speed
- baserunning
- stealing

守備:
- arm_strength
- fielding
- throwing
- position_aptitude

捕手:
- catching
- game_calling

投手:
- velocity_kmh
- control
- stamina
- stuff
- strikeout
- groundball
- composure
- pitch_repertoire

## Scale

通常能力は1〜100。

表示帯:
- S 90〜100
- A 80〜89
- B 70〜79
- C 60〜69
- D 50〜59
- E 40〜49
- F 30〜39
- G 1〜29

球速のみkm/h。

## Team strength

学校masterに固定能力を持たせない。

```
PlayerAbilitySnapshot
↓
StartingLineup / PitchingStaff
↓
TeamStrengthSnapshot
```

初期configには、打撃・走塁・守備・投手の集約重みを置いた。

これらは `design_default_not_tuned` であり校正済みではない。
Stage 13B-2/13B-3の大量監査で変更する前提。

## Version / revision

### v2へ上げる
- abilityの意味変更
- 単位変更
- field削除
- 根本的な構造変更

### revisionを上げる
- mean
- stddev
- weight
- threshold
- clamp

数値だけの変更でもseed結果は変化する。

そのため将来のPlayerAbilitySnapshotには:

- config_id
- revision
- canonical_config_sha256

を保存する。

## RNG namespace

能力ごとに独立させる。

例:

`player_ability_v1:{reference_year}:{player_id}:contact`

`player_ability_v1:{reference_year}:{player_id}:fielding`

`player_pitch_v1:{reference_year}:{player_id}:slider`

contactの生成処理を変更してもfieldingまで連鎖変更しにくくする。

## Validation

`game_core/ability_config.py` を追加。

標準ライブラリのみで:

- config_id
- revision
- catalog ability_id
- display bandの重複/欠落
- weight合計=1.0
- 学校固定能力禁止
- version付きnamespace

を検査する。

## 次工程

Stage 13B-2:

1. PlayerAbilitySnapshot dataclass
2. config読み込み
3. 22能力のseed再現生成
4. 位置・学年条件
5. 代表golden seed
6. 大量生成監査

ここで初めて分布を実測し、現在の暫定mean/stddevを調整する。

Stage 13B-3でスタメン・投手陣を選択し、TeamStrengthSnapshotを実装する。
