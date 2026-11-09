# Screen configuration

正式な画面（game_definition.md §9、ADR-044）で使う設定。

- `screen_v1.json`: まとめて進めるときに止まる「大きな場面」の条件など。値の意味は `notes_ja` に書く。
- `school_short_names_v1.json`: 画面の短い校名で、規則に合わない学校を個別に直す（`phase2_engine/screen/school_names.py`）。
- `competition_short_names_v1.json`: 一覧で使う大会の短い名前で、規則に合わない大会を個別に直す（`phase2_engine/screen/competition_names.py`）。
- `tile_map_v1.json`: 都道府県のタイル地図のマスの並び（列・行）と、色分けに使う地区の季節（`phase2_engine/screen/web/app.js` の `tileMap`）。
