# Stage 13B-3 初期学校strength分布監査

## 監査条件

- reference year: 2026
- seeds: 2026100701 / 2026100702 / 2026100703
- 各seed: 1,000校
- 合計: 3,000校
- 1校20人
- underlying player snapshots: 60,000人
- Stage 13Aと同じ5P / 2C / 13野手構造
- team_strength_v1 revision 2

実在校の強豪度教師データによる校正ではなく、生成式の健全性とseed安定性を確認する合成監査である。

## 主な結果

3seed平均レンジ:

- batting_strength: 54.2754〜54.3821
- defense_strength: 58.9475〜59.2215
- ace_strength: 58.6266〜58.7752
- pitching_strength: 54.5820〜54.7395

各metricのseed間mean差は0.5未満。

境界1 / 100への張り付きは学校集約値では確認されず、計算式の破綻はない。

## 解釈

スタメン選抜により、個人能力母集団の平均50前後より学校値はやや上側へ移動する。これは「20人から先発を選ぶ」ことによる自然なselection effectである。

一方、学校ごとの選手能力分布が現時点では同じ母集団のため、batting_strengthの標準偏差は約1.8、pitching_strengthは約2.85と学校間差が圧縮されている。

これはTeamStrength集約式の不具合ではない。Stage 13B-1でreservedとしていた recruiting / player intake strength がまだ未導入であることが主因。

## 判断

- TeamStrength集約式: 初期baselineとして採用
- team_strength_v1: status=design_default_not_tunedを維持
- 学校固定ratingの直接加算: 導入しない
- 次回調整: 学校ごとの入部選手母集団差を導入した後に再監査

実在強豪校に合わせるためにTeamStrengthへ直接ボーナスを足すのではなく、選手生成・入部層を通じて結果として学校差が現れる設計を優先する。
