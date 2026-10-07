# Stage 13B-3 実装報告

## 実装内容

Stage 13B-2のPlayerAbilitySnapshotから以下を生成する基盤を実装した。

- StartingLineup
- PitchingStaff
- TeamStrengthSnapshot
- 学校strength CSV export
- 学校strength分布監査
- CLI

## StartingLineup

9守備位置を本職候補から1名ずつ選出する。

Pはpitcher quality、Cは打撃＋捕手守備、その他は打撃＋守備＋走塁で決定する。

打順も選手能力から決定し、同点時はplayer_idで固定する。

## PitchingStaff

全投手をpitcher quality順に並べる。

5投手構造ではace / second / third / depth_1 / depth_2となる。

StartingLineupのPとaceは同一選手であることをvalidatorで保証する。

## TeamStrengthSnapshot

10指標を1〜100で生成する。

- batting
- contact
- power
- discipline
- running
- defense
- ace
- pitching depth
- bullpen
- pitching

学校masterの固定戦力値は使わない。

## config

`team_strength_v1.json` をrevision 2へ更新し、スタメン選抜・打順の重みを `selection` として追加した。

数値をPythonへ埋め込まず、今後の調整時にconfig revisionとhashで追跡できる。

## 分布監査

3seed×1,000校=3,000校を監査した。

詳細:
`audits/phase3/stage13b3/stage13b3_strength_distribution_20261007.csv`

主要meanはseed間で安定している。

一方、学校ごとの選手母集団差がまだないため学校strengthの分散は小さい。この点は次工程の選手流入/学校差モデルで扱う。

## Stage 12P接続

Stage 12PのResultView契約は維持し、能力ベースscore generatorを後段差替できる方針を設計文書へ固定した。

- generated_v1: 暫定互換
- ability_model_v1: 次工程
- score override: 実績スコアとして最優先維持

## 次工程候補

Stage 13B-4として学校ごとの選手流入差を導入してTeamStrength分布を再監査する。

その後、Stage 13CでTeamStrengthSnapshotを使う能力ベース試合イベント/個人成績生成へ進む。
