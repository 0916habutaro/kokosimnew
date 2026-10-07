# ADR-006: 学校差は入部選手母集団を通して形成する

- Status: Accepted
- Date: 2026-10-07

## Context

Stage 13B-3ではTeamStrengthを選手能力から算出できるようになったが、全学校が同じPlayerAbility母集団を使うため学校間差が小さい。

最終TeamStrengthへschool_id由来の固定bonusを直接加算すれば差は簡単に作れるが、個々の選手能力と学校戦力の整合性が崩れる。

## Decision

学校差は `SchoolIntakeProfile` を通した入部選手母集団差として生成する。

- 学校に持続するprogram成分
- 入学年度ごとのcohort成分
- 選手能力生成前後の能力値調整
- TeamStrengthは調整済み選手だけから従来どおり算出

直接TeamStrength bonusは禁止する。

またprogram成分は実在校の実力評価ではなく、架空選手生成用の合成潜在値として扱う。

## Consequences

### 利点

- 選手能力と学校戦力の整合性が保たれる
- 複数学年に学校カラーが残る
- cohort変動により毎年同じ戦力にならない
- 将来、入部・卒業・新入生生成へ自然に接続できる
- JSON調整で学校間分散を変更できる

### 注意点

- 実在校の強弱を表すものではない
- 現時点の数値は design_default_not_tuned
- 実データ校正を行う場合は別ADRまたはrevision履歴を残す
