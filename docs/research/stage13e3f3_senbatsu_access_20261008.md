# Stage 13E-3F-3 第2工程：選抜出場校の可変枠アクセス判定

日付: 2026-10-08

## 不具合

2026年の選抜大会 `CMP000001` から春季県大会に出場する学校を抽出するアクセス規則は、`source_result_selector=participant_from_destination_prefecture` と `quota_mode=all_matches` を使用する。神奈川春 `CMP000095 / ACR000008` および愛知春 `CMP000113 / ACR000012` は、生成試合で同県から2校が選抜出場した一方、`observed_2026_count=1` が生成結果の絶対的上限として扱われ、`FAIL` となっていた。

## 修正

- `quota_mode=all_matches`: 選抜の生成参加校から該当県の全出場校を列挙し、生成した人数を `expected_count` に使用する。該当学校が0校でも架空の免除対象を作成しない。
- `fixed` 等それ以外のモード: 従来どおり `observed_2026_count` または `quota` と照合する。
- `observed_2026_count=1` は公式2026年実績として元CSVに残し、ゲーム内の生成人数に上書きしない。
- 後回し項目管理台帳の `ACR000008`・`ACR000012` を `resolved` に更新。

## テスト

追加した4ケース：生成対象県2校、生成対象県1校、fixed枠の超過はFAIL、生成対象県0校。既存unittestと合わせてGitHub Actionsで検証する。

## 次工程

春季pre-MAINの日付未verified 20件と北海道春の1件は台帳に残し、裏付けのある日付だけをverified化する。神宮の個別試合日は2026-10-17以降に公開される公式組み合わせで再確認する。
