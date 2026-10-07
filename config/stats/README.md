# Player stats configuration

Stage 13D以降の個人成績read model・ランキング表示に使うversion付き設定。

## player_rankings_v1.json

Stage 13D-1の初期設定。

- 率指標の丸め桁
- 打者ランキング規定PA
- 投手ランキング規定outs
- ranking metricと昇順/降順

## 重要

この規定値はゲーム内ランキング表示用の設計値であり、高校野球の公式表彰規定を意味しない。

SQLiteへ保存する正本はGameStatsの整数count。

AVG / OBP / SLG / OPS / ERA / WHIP等はread modelで毎回導出する。

調整だけなら同じconfig_idのrevisionを上げる。意味・構造を変える場合はv2。
