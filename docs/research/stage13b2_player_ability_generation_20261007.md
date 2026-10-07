# Stage 13B-2 PlayerAbilitySnapshot・能力生成・分布監査

作成日: 2026-10-07

## 目的

Stage 13B-1で固定した能力設計を実装し、Playerから再現可能なPlayerAbilitySnapshotを生成する。

## 実装

### game_core/abilities.py

追加:

- PitchAbility
- PlayerAbilitySnapshot
- PlayerAbilityGenerator
- validate_ability_snapshot
- write_ability_snapshots_csv

### game_core/ability_audit.py

追加:

- AbilityAuditRow
- audit_ability_snapshots
- write_ability_audit_csv

監査統計:

- n
- mean
- stdev
- min/max
- P01/P05/P25/P50/P75/P95/P99
- lower/upper clip rate

dimension:

- overall
- grade
- position
- pitch_type

### game_core/ability_cli.py

能力CSV生成と分布監査をCLIから実行可能。

例:

```bash
python -m game_core.ability_cli \
  --data-dir data \
  --config-dir config/abilities \
  --year 2026 \
  --seed 2026100701 \
  --school-limit 1000 \
  --output out/abilities.csv \
  --audit-output out/ability_audit.csv
```

## 能力対象

全選手:

- 打撃11能力
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

## 球種

投手2〜4球種。

- four_seam必須
- その他をseed選択
- quality
- command
- usage
- usage合計100

## Config provenance

snapshotにcatalog / scale / generationの:

- config_id
- revision
- canonical_sha256

を埋め込む。

## Golden seed

`audits/phase3/stage13b2/golden_seed_v1.json`

学校master変更に影響されない合成Player IDを3人固定。

- 1年投手
- 2年捕手
- 3年遊撃手

主要能力・主守備適性・投手球種を回帰fixture化。

## 大量分布監査

3seed×20,000人 = 60,000人。

結果:

- 通常能力の上下限張り付き: 最大0.06%以下
- 球速上限張り付き: 最大0.04%
- 主守備位置適性100: 2.63〜2.85%
- contact mean: 50.72〜50.85
- velocity mean: 135.40〜135.46 km/h
- pitch count mean: 2.986〜3.005

詳細は:

`docs/tuning/stage13b2_initial_distribution_audit_20261007.md`

## 初回調整判断

数値変更なし。

分布上の破綻がないため、根拠のない調整は行わない。

revision 1を初期baselineとして採用し、実在高校野球の成績・球速・球種構成と比較できるStageで再調整する。

## 次工程

Stage 13B-3:

1. StartingLineup / PitchingStaff
2. 選手能力からTeamStrengthSnapshot算出
3. batting/contact/power/discipline/running/defense
4. ace/depth/bullpen/pitching
5. 学校strength分布監査
6. Stage 12P generated_v1との接続方針確定

その後Stage 13Cで試合内イベントと個人成績へ進む。
