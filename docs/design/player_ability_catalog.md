# 選手能力カタログ v1

機械可読の正本は `config/abilities/ability_catalog_v1.json`。
この文書は人間向けの要約。

| ability_id | 対象 | 尺度 | 意味 |
|---|---|---|---|
| contact | 野手 | 1-100 | バットに当てインプレーへ持ち込む力 |
| power | 野手 | 1-100 | 強い打球・長打を生む力 |
| plate_discipline | 野手 | 1-100 | ボール球を見極める力 |
| strikeout_resistance | 野手 | 1-100 | 三振を避ける力 |
| bunt | 野手 | 1-100 | バント技術 |
| speed | 共通 | 1-100 | 純粋な走速度 |
| baserunning | 野手 | 1-100 | 進塁判断 |
| stealing | 野手 | 1-100 | 盗塁技術 |
| arm_strength | 共通 | 1-100 | 肩の強さ |
| fielding | 共通 | 1-100 | 捕球・打球処理 |
| throwing | 共通 | 1-100 | 送球精度 |
| catching | 捕手 | 1-100 | 捕球・ワンバウンド処理 |
| game_calling | 捕手 | 1-100 | 配球・投手連携 |
| velocity_kmh | 投手 | km/h | 基準球速 |
| control | 投手 | 1-100 | 制球 |
| stamina | 投手 | 1-100 | 投球持久力 |
| stuff | 投手 | 1-100 | 球速以外も含む打ちにくさ |
| strikeout | 投手 | 1-100 | 三振を奪う総合力 |
| groundball | 投手 | 1-100 | ゴロを打たせる能力 |
| composure | 投手 | 1-100 | 高圧状況での安定性 |
| position_aptitude | 守備 | position別1-100 | 各守備位置の習熟度 |
| pitch_repertoire | 投手 | 球種リスト | quality / command / usage |

## 混同しないもの

- contact ≠ 打率
- power ≠ 本塁打数
- plate_discipline ≠ 出塁率
- speed ≠ 盗塁成功率
- arm_strength ≠ throwing
- fielding ≠ position_aptitude
- velocity_kmh ≠ 投手総合力
- game_calling は投手能力を直接上書きしない

## pitch_repertoire

各球種は少なくとも次を持つ。

- pitch_type
- quality
- command
- usage

単一の「変化球70」のような値へ潰さない。

## 将来追加するとき

新能力を追加する場合は、まず以下を明記する。

1. 何を表すか
2. 既存能力と何が違うか
3. 試合モデルのどこで使うか
4. 何の成績値とは別物か
5. v1互換で追加可能か、v2が必要か
