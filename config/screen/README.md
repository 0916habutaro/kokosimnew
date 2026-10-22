# Screen configuration

正式な画面（game_definition.md §9、ADR-044）で使う設定。

- `screen_v1.json`: まとめて進めるときに止まる「大きな場面」の条件など。値の意味は `notes_ja` に書く。
- `school_short_names_v1.json`: 画面の短い校名で、規則に合わない学校を個別に直す（`phase2_engine/screen/school_names.py`）。
