# 選手の設定

- `player_names_v1.json`：選手の名前（苗字＋名前）と出身の都道府県の重み。使うのは `game_core/player_names.py`、材料は `data/generation/player_names/`（`game_definition.md` §3.5）
- `player_growth_v1.json`：選手の成長（毎月・公式戦の出場・成長の型・潜在能力・上限に近いほど伸びにくい係数）。使うのは `game_core/player_growth.py`（`game_definition.md` §3.1）
