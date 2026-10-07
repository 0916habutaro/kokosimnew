# Stage 13B-4 初期 School Intake 分布監査

作成日: 2026-10-07

## Status

`design_default_not_tuned`

本監査は実装初期値の分布健全性を確認するものであり、実在高校野球の戦力分布へ校正済みであることを意味しない。

## Before

Stage 13B-3では、全学校が同一のPlayerAbility母集団から選手を生成していた。

そのためTeamStrength集約式自体は安定していたが、学校間の戦力差が小さかった。

Stage 13B-4では、この問題を最終TeamStrengthへの固定school bonusで解決しない。

## Problem

必要なのは次の両立。

1. 学校間に明確な戦力差が出る
2. 全体平均を大きく押し上げたり押し下げたりしない
3. 選手能力と学校戦力が整合する
4. 同じ学校でも毎年同じ強さにならない
5. 実在校の事実上の格付けにしない

## Change

`school_intake_v1.json` を追加。

合成入部品質:

```
intake_quality_z
  = 0.8 * program_quality_z
  + 0.6 * cohort_quality_z
```

- program: school_id単位で持続
- cohort: school_id + entry_year単位で変動
- 0.8² + 0.6² = 1.0
- intake_quality_zは -2.5〜+2.5へclip

この値を選手能力へ適用し、その後のTeamStrength計算式はStage 13B-3と同じものを使う。

## Audit setup

- reference year: 2026
- seeds:
  - 2026100701
  - 2026100702
  - 2026100703
- synthetic school IDs: 各seed 1,000校
- 1校: 20選手
- baselineとschool_intake_v1を同一school_id・seedで対比較
- 各model: 3,000チーム
- underlying ability generation:
  - baseline 60,000 player snapshots
  - intake 60,000 player snapshots
- audit rows: 66

正本:

`audits/phase3/stage13b4/stage13b4_intake_team_distribution_20261007.csv`

## After

### batting_strength

| seed | baseline mean | intake mean | baseline sd | intake sd | sd ratio |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2026100701 | 54.1991 | 54.4310 | 1.7381 | 4.3103 | 2.480 |
| 2026100702 | 54.1709 | 54.2875 | 1.7113 | 4.2374 | 2.476 |
| 2026100703 | 54.0872 | 53.9747 | 1.7013 | 4.2670 | 2.508 |

P05/P95はintake導入後、おおむね47→61まで広がった。

### pitching_strength

| seed | baseline mean | intake mean | baseline sd | intake sd | sd ratio |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2026100701 | 48.2908 | 48.5063 | 2.4052 | 4.7659 | 1.981 |
| 2026100702 | 48.2869 | 48.2116 | 2.3198 | 4.5583 | 1.965 |
| 2026100703 | 48.2275 | 48.0892 | 2.3607 | 4.7620 | 2.017 |

P05/P95はintake導入後、おおむね40.4→56前後まで広がった。

### defense_strength

- baseline sd: 2.3448〜2.3873
- intake sd: 3.9296〜4.1357
- 約1.67〜1.74倍

### ace_strength

- baseline sd: 3.1836〜3.2181
- intake sd: 5.0262〜5.2419
- 約1.58〜1.63倍

### latent intake distribution

roster平均 `intake_quality_z`:

- mean: -0.0378〜0.0429
- sd: 0.8745〜0.8914
- P05: -1.51〜-1.44
- P95: 1.39〜1.48

program component:

- mean: -0.0365〜0.0309
- sd: 1.0130〜1.0396

合成潜在値の中心はほぼ0を維持している。

## Mean drift

代表4指標でintake導入後のbaseline比mean差を確認。

- batting_strength: -0.1125〜+0.2319
- defense_strength: -0.1426〜+0.1347
- ace_strength: -0.1386〜+0.2151
- pitching_strength: -0.1383〜+0.2155

今回の目的である「平均値を大きく動かさず、学校間差を広げる」は満たしている。

## Decision

初期値として採用する。

理由:

- 学校間分散が明確に増えた
- 全体平均のドリフトが小さい
- 選手能力を経由して学校戦力差が形成される
- program/cohort分離により持続性と年度変動を両立できる
- baseline generatorを残して今後も差分監査できる

ただし `design_default_not_tuned` を維持する。

現時点では「現実の強豪校・中堅校・弱小校の分布を再現した」とは判断しない。

## Next tuning candidates

Stage 13C以降の試合モデルを通した後に以下を再監査する。

- 上位5%と下位5%の勝率差
- 地区・県大会での番狂わせ率
- 投打の相関が強すぎないか
- 強豪校のdepthが過度に固定化しないか
- cohort変動で数年単位の盛衰が出るか
- 将来、実績データで校正する場合のhistorical calibration方針
