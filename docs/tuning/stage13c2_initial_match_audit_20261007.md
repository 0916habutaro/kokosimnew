# Stage 13C-2 初期能力ベース試合モデル監査

作成日: 2026-10-07

## Status

`design_default_not_tuned`

本監査は「試合エンジンとして成立しているか」「能力差が勝敗へ反映されているか」を確認する初期監査である。

実在高校野球の得点・打撃・投球分布へ校正済みであることを意味しない。

## Before

Stage 12Pの `generated_v1` はTournamentEngineが先に決めたwinnerを維持したまま、勝者得点と敗者得点をseed再現で付ける暫定モデルだった。

Stage 13C-1で能力モデル用contractを固定したが、実際の打席・塁・out・inning進行はまだなかった。

## Problem

Stage 13C-2では以下を同時に成立させる必要がある。

1. PlayerAbility差が打席eventへ反映される
2. eventの積み上げからscoreが決まる
3. scoreと個人成績が完全に整合する
4. 強い学校ほど勝ちやすいが、必勝にはならない
5. team1/team2順序だけで大きな勝率biasを作らない
6. 乱数seedで完全再現できる
7. 数値を後からJSONだけで調整できる

## Change

`match_simulation_v1.json` をrevision 2へ更新。

追加した調整領域:

- plate_appearance_model
- situational_events
- baserunning
- pitching_usage
- hard_max_innings

通常eventのbase probability合計は1.0。

event weightは打者・投手・守備能力で乗算調整し、最終scoreへ固定bonusは加えない。

## Audit setup

- reference year: 2026
- seeds:
  - 2026100701
  - 2026100702
  - 2026100703
- 各seed:
  - synthetic school selection: 240校
  - games: 1,000
- total games: 3,000
- school生成:
  - PlayerRosterGenerator
  - SchoolAwarePlayerAbilityGenerator
  - TeamStrengthGenerator
- 全試合:
  - MatchSimulator
  - Stage 13C-1 reconciliation通過必須

正本:

`audits/phase3/stage13c2/stage13c2_match_distribution_20261007.csv`

## Result

### 得点分布

| seed | mean total runs | P50 | P95 | max | winner mean | loser mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026100701 | 9.910 | 9 | 19 | 33 | 6.978 | 2.932 |
| 2026100702 | 9.892 | 9 | 19 | 40 | 6.897 | 2.995 |
| 2026100703 | 9.800 | 9 | 19 | 28 | 6.818 | 2.982 |

seed間の平均総得点差は0.11以内で安定。

一方、max 28〜40点の上側tailは現実校正時の重点監視対象とする。

### 接戦・完封・延長

| seed | 1点差 | 完封 | 延長 |
| --- | ---: | ---: | ---: |
| 2026100701 | 24.5% | 12.0% | 7.1% |
| 2026100702 | 25.5% | 10.7% | 7.9% |
| 2026100703 | 26.2% | 12.2% | 8.2% |

### team2 bias

team2勝率:

- 50.2%
- 48.7%
- 52.3%

大きな表裏順序biasは確認されなかった。

### 能力差と勝率

全matchupで、監査用overall

```
0.45 * batting_strength
+ 0.45 * pitching_strength
+ 0.10 * defense_strength
```

が高い側を「stronger」とした。

overall stronger win rate:

- 61.4%
- 62.2%
- 62.2%

戦力差別:

| edge | seed1 | seed2 | seed3 |
| --- | ---: | ---: | ---: |
| 0〜2 | 49.1% | 54.4% | 52.4% |
| 2〜5 | 60.5% | 61.2% | 57.0% |
| 5〜10 | 69.8% | 66.5% | 76.3% |
| 10以上 | 84.0% | 90.7% | 75.8% |

近い戦力ではほぼ五分、差が広がるほどstronger側勝率が上昇する。

seed3の10以上が5〜10よりわずかに低いが、方向性全体は維持されている。bin件数も含めた本格校正は後続で行う。

### event rate

| metric | seed1 | seed2 | seed3 |
| --- | ---: | ---: | ---: |
| SO / PA | 19.28% | 19.45% | 19.38% |
| BB / PA | 7.84% | 8.03% | 7.98% |
| HBP / PA | 1.02% | 0.94% | 0.98% |
| H / PA | 22.81% | 22.89% | 22.93% |
| HR / PA | 2.62% | 2.61% | 2.58% |
| ROE / PA | 1.84% | 1.68% | 1.77% |
| SH / PA | 0.46% | 0.41% | 0.41% |
| SF / PA | 0.95% | 1.00% | 0.94% |

seed間は安定している。

### pitcher usage

平均使用投手数 / team:

- 3.176
- 3.213
- 3.191

ace固定完投モデルにはなっておらず、PitchingStaffが実際に使われている。

## Decision

revision 2をStage 13C-2初期モデルとして採用する。

理由:

- 3,000試合すべて完走しreconciliationを通過
- seed間分布が安定
- team2 biasが小さい
- 能力差が勝率差へ変換される
- 接戦・完封・延長が一定割合発生
- event rateがseed間で安定
- 複数投手が使用される

ただし `design_default_not_tuned` を維持する。

## Not yet calibrated

以下はまだ「現実的」と断定しない。

- 平均得点
- 高得点tail
- SO / BB / HR率
- 延長率
- 強豪勝率
- 投手使用数

実在大会データとの比較は別工程。

## Next tuning candidates

- 2026実試合結果から1試合総得点・点差・完封・延長分布を取得
- 打撃成績データが確保できる場合はH/PA, BB/PA, SO/PA, HR/PAを校正
- edge binごとの試合数も監査CSVへ追加
- コールドゲーム導入後の得点tail再監査
- タイブレーク導入後の延長率再監査
- 投手交代と継承走者責任の精密化
