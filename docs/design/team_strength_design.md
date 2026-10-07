# 学校能力算出設計 v1

## 原則

学校に固定の `batting=80` や `pitching=75` を持たせない。

学校能力は、その時点の選手・起用・状態から作る派生snapshotとする。

```
PlayerAbilitySnapshot
        ↓
StartingLineup / PitchingStaff
        ↓
TeamStrengthSnapshot
```

## 出力候補

- batting_strength
- contact_strength
- power_strength
- discipline_strength
- running_strength
- defense_strength
- ace_strength
- pitching_depth_strength
- bullpen_strength
- pitching_strength

試合シミュレーションでは単一overallではなく複数componentを使う。

## 打撃

中心はスタメン9人。

控えは「層の厚さ」として限定的に反映する。

初期重みは `config/abilities/team_strength_v1.json` に置く。
これは校正済み値ではなく、Stage 13B-3で大量監査して調整する。

## 投手

単純な全投手平均にしない。

- エース
- 2番手
- 3番手
- 残りの層

を別重みで集約する。

これにより「エース突出型」と「投手層型」を区別する。

将来は日程・前日登板・疲労を後段で適用するため、base pitching strength自体には疲労を混ぜない。

## 守備

実際の守備配置から計算する。

選手ごとに:

- fielding
- throwing
- arm_strength
- position_aptitude

を使用する。

捕手は:

- catching
- game_calling

を追加する。

守備位置重要度もJSON側で調整可能にする。

## 走塁

- speed
- baserunning
- stealing

を分けて集約する。

## 学校ブランド

将来 `program_reputation`, `recruiting_strength`, `coaching_quality` を追加する場合でも、試合時team strengthへ直接加算しない。

```
強豪校
→ 良い新入生が入りやすい
→ 選手能力が高くなりやすい
→ 結果として強い
```

という因果にする。

## Snapshotである理由

同じ学校でも、

- 春
- 夏
- 3年生引退後の秋
- エース登板可能日
- エース連投後

で強さが変わるため。

学校masterの固定能力にはしない。
