# Stage 13B-4 学校別入部選手品質モデル 実装報告

作成日: 2026-10-07

## 目的

Stage 13B-3のTeamStrengthは選手能力から算出できるようになったが、学校ごとの選手流入差がなく学校間分散が小さかった。

Stage 13B-4では、学校masterへ固定の学校戦力を持たせず、入部選手の能力母集団を変化させることで学校差を形成する。

## 実装

### 新規 config

`config/abilities/school_intake_v1.json`

- program component
- cohort component
- combined clip
- 能力別 adjustment per quality z
- versioned RNG namespace
- 実在校評価ではないことを機械可読rulesで固定
- direct TeamStrength bonus=false

### 新規 model

`game_core/school_intake.py`

- SchoolIntakeProfile
- SchoolIntakeModel
- IntakeAdjustedPlayerAbilitySnapshot
- SchoolAwarePlayerAbilityGenerator

### program / cohort

program namespace:

`school_intake_v1:program:{school_id}`

cohort namespace:

`school_intake_v1:cohort:{school_id}:{entry_year}`

program成分は同一学校内で学年間に持続し、cohort成分は入学年度ごとに変わる。

### 能力調整

Stage 13B-2のPlayerAbilityGeneratorをbaselineとして維持したまま、その出力にSchoolIntakeProfileを適用する。

調整対象:

- 打撃・走塁・守備scalar
- catcher-only
- pitcher abilities
- 主守備位置適性
- pitch quality
- pitch command

Stage 13B-4では球種数・球種種類・usageは変更しない。

## TeamStrength provenance

TeamStrengthSnapshotへ追加:

- school_intake_config_id
- school_intake_config_revision
- school_intake_config_sha256

baseline snapshotとintake snapshotを混在させたTeamStrength生成はvalidatorで拒否する。

## CLI

通常:

- `game_core.ability_cli`: school-aware
- `game_core.team_strength_cli`: school-aware

比較監査用:

`--baseline-no-school-intake`

を指定するとStage 13B-2 baselineへ戻せる。

## Config governance

`ability_config.py` に `validate_school_intake()` を追加。

主な検証:

- program/cohort stddev > 0
- component weightの二乗和=1
- adjustment ability IDがcatalogと一致
- direct_team_strength_bonus=false
- synthetic_not_real_school_rating=true
- applied_before_team_strength=true
- cohort_key=entry_year
- namespace version付き

## 回帰テスト

Stage 13B-4専用テストで以下を確認。

- profile seed再現
- program componentの学年間持続
- cohort componentの年度差
- school_id差
- intake clip
- player provenance
- 正負qualityによる能力方向性
- baseline generator維持
- TeamStrength provenance
- baseline/intake混在拒否
- 学校間TeamStrength分散増加
- CSV provenance
- CLI baseline switch

## 大量監査

3seed × 各1,000 synthetic schools。

baselineとschool_intake_v1を同じschool_id・seedで比較。

代表結果:

- batting sd: 1.70〜1.74 → 4.24〜4.31
- defense sd: 2.34〜2.39 → 3.93〜4.14
- ace sd: 3.18〜3.22 → 5.03〜5.24
- pitching sd: 2.32〜2.41 → 4.56〜4.77

代表指標のmean driftは最大でも約0.24。

学校差を増やしつつ、全体平均をほぼ維持した。

## 解釈上の注意

このモデルは実在校の強さを推定したものではない。

school_idは乱数namespaceの識別に使うだけであり、現時点では学校名・地域・過去大会成績を強弱へ変換していない。

したがって、特定の実在校に生成された高いprogram_quality_zを「実際に強豪だから」と解釈してはいけない。

## 次工程

Stage 13B-4完了後はStage 13Cへ進む。

- 能力ベース試合モデル
- 打席・投球等の試合イベント
- 個人成績生成
- ResultViewの `ability_model_v1` 接続
- TeamStrength差が実際の勝率差へどう変換されるかの監査

Stage 13C監査結果を見てschool_intake_v1 revisionを再調整する。
