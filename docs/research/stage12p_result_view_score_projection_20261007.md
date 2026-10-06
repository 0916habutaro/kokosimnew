# Stage 12P 観戦用試合結果read model・スコア生成基盤

作成日: 2026-10-07

## 背景

Stage 12C〜12Lで大会構造・勝敗・進出は生成できるが、試合結果出力は学校IDとwinner/loserが中心で、ゲーム画面で眺めるための「○○高校 5-3 △△高校」のような結果表示がまだない。

ココシミュNewは育成操作より試合結果・成績閲覧を重視するため、GUIより先に表示用の試合結果read modelを用意する。

## 設計方針

大会エンジンのwinner決定には手を入れない。

1. TournamentEngineが従来通りwinner/loserを確定
2. Stage 12Pが後段で表示用スコアを付与
3. 学校IDを表示名へ解決
4. GUI/DBが読みやすい1試合1行CSVへ変換

この分離により、既存の大会構造回帰を壊さない。

## generated_v1

現段階では選手・チーム能力の試合シミュレーションは未導入なので、seed再現可能な暫定スコア生成を行う。

namespace:

`score_v1:{competition_id}:{year}:{match_id}`

生成規則:

- 敗者得点: 0〜9から重み付き抽選
- 点差: 1〜8から重み付き抽選
- 勝者得点 = 敗者得点 + 点差
- 大会エンジンが決めたwinner側へ高得点を割り当てる
- 同点は生成しない

これは最終的な野球試合モデルではなく、表示・保存・GUI接続の契約を先に固定するための暫定実装。

## 実スコアoverride

`match_id -> [team1_score, team2_score]`

または

`match_id -> {"team1_score": 5, "team2_score": 2}`

を指定できる。

overrideは次を検証する。

- 0以上の整数
- 同点不可
- 大会winnerと高得点側が一致
- unknown match_id不可
- byeへのscore指定不可

したがって、後から2026実績スコアを投入する場合も同じread modelを利用できる。

## 出力

`<competition_id>_<year>_result_view.csv`

主な列:

- match_id
- stage_code / phase_code / round
- team1_id / team1_name / team1_score
- team2_id / team2_name / team2_score
- winner_id / winner_name
- loser_id / loser_name
- score_source
- result_text

表示例:

`A高校 5-3 B高校`

不戦勝は得点を空欄とし、`A高校 不戦勝` とする。

## CLI

既存の `phase2_engine.cli` へ接続する。

`--result-dir` を指定すると従来のsummary/matches/placementsに加えてresult_view.csvを生成する。

実スコアを与える場合:

```bash
python -m phase2_engine.cli \
  --demo hokkaido-autumn \
  --seed 2026100701 \
  --result-dir out \
  --score-override-json exact_scores.json
```

## 今後

Stage 12Pで「表示用試合結果」の契約ができたため、次は以下へ進められる。

- GUIの大会結果一覧
- 日付別試合一覧
- 学校別戦績
- 選手/チーム能力を使った本格スコアシミュレーション

本格試合シミュレーション導入時も `ResultViewRow` の出力契約は維持する。
