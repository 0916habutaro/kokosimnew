# Stage 13E-3G-27：広島県2026春秋の残り7地区・公式抽選図を画像で確認

実施日：2026-10-09

## 結論と証拠の精度

広島県高野連の公式大会ページ内にリンクされた令和8年度春秋の公式組み合わせPDFについて、**残り7件ともGoogle Driveの表示ページにある「Image」リンクを開き、地区・季節・年度が分かる組み合わせ図の画像を実際に視認**できた。Stage24で確認した2026秋季西部1件を加え、**計8/8地区・季節**の公式図の大枠を照合できる状態になった。

公式掲載元：https://hiroshima.hhbf1950.or.jp/大会関連/硬式部各種大会

2026年度の公式資料：
- 春西：https://drive.google.com/file/d/1H3_Nxm9VjTBdM-cgVWmX0X9v3CiDNkMr/view?usp=sharing
- 春北：https://drive.google.com/file/d/1vKI_4AFyxkvlFw-ZaJ6TMKBDXpPYeyFz/view?usp=sharing
- 春南：https://drive.google.com/file/d/1gSVMVuzfjIEgklHdTgXi8eqj0OUloPS_/view?usp=sharing
- 春東：https://drive.google.com/file/d/1Su5If9rOmkfLvMLuUiPjBpbOhkd27qPT/view?usp=sharing
- 秋西（Stage24確認済）：https://drive.google.com/file/d/1VxVW_r_L5MwnP3hkqZToGe3o5StK5NQ-/view?usp=sharing
- 秋北：https://drive.google.com/file/d/11nILxjp_0ghyw-ir8u3EjeKXHBL_mpQh/view?usp=sharing
- 秋南：https://drive.google.com/file/d/1rdH-iz4Gqc4jJLPHoPrpJlST6dfZoxfO/view?usp=sharing
- 秋東：https://drive.google.com/file/d/1pfsrSTuhiH5_pmPvyvCBObonztTF4dd0/view?usp=sharing

**重要：原本PDFバイト自体は取得していない。** 表示画像での大会方式のマクロ確認であり、試合の全番号・各敗者が移る先・全試合カードの公式番号付きDAGを8件すべて完全転記した意味ではない。小文字・矢印が判読不十分な個所には予想値を採用しない。

## 視認した地区ごとの基本構造と別ソースの集計値

公式画像で各季節地区の一次ゾーンA～D/E/Fと一次予選から二位校等の試合群への階層を確認した。下表の一次枠・出場枠は**画像上のゾーン概略＋既登録の学校別2026結果・公式県大会定員との突合**により再検証する。二位校イベント件数・追加決定戦イベント件数は**SportsOnlineの出版社子大会インデックス由来**であって、公式画像中の全対戦矢印が証明されたという意味ではない。

| 季節地区 | 一次ゾーン | 一次出場枠 | その他の予選出場枠 | 本戦直接免除 | 本戦計 | 子大会二位校／追加決定戦 |
|---|---:|---:|---:|---:|---:|---|
| 春西 | 4 | 4 | 2 | 1 | 7 | 4／1 |
| 春北 | 4 | 4 | 3 | 0 | 7 | 4／2 |
| 春南 | 6 | 6 | 3 | 0 | 9 | 6／3 |
| 春東 | 5 | 5 | 4 | 0 | 9 | 4／0 |
| 秋西 | 4 | 4 | 3 | 0 | 7 | 4／1 |
| 秋北 | 4 | 4 | 2 | 0 | 6 | 4／2 |
| 秋南 | 6 | 6 | 4 | 0 | 10 | 6／4 |
| 秋東 | 5 | 5 | 4 | 0 | 9 | 3／1 |

春季7+7+9+9=32、秋季7+6+10+9=32。**春西部の選抜出場校直接免除1枠**を追加の予選通過校として二重集計しない。春秋計64季節枠は実予選63＋直接免除1。

### 年度内でも形式が一様ではない

- 西部と北部は春秋とも一次4ゾーン。ただし北部は春7・秋6、秋西7とは異なる。
- 南部は春秋とも一次6ゾーン。春9・秋10の出場枠差がある。
- 東部は春秋とも一次5ゾーン、出場9枠。ただし出版社の「二位校」「追加決定戦」イベントの構成は季節で異なる。
- 秋西の2026公式図はStage24のA/B二位校直接出場＋C/D二位校横断1枠が年度限定で確かめられている。**この2026秋西の詳細マクロを残り7地区に自動移植しない**。
- 敗者復活戦敗戦後の追加挑戦は春北／春東／秋南／秋東の実績例があるが、2026二次結果の観測のみで翌年の敗者再挑戦を一般化しない。

## 変更ファイル

- `data/competitions/2026/hiroshima_other_seven_official_image_macro_2026.csv`：新規画像確認7件、公式PDFリンク・年度・地域・一次ゾーン数・出版社イベント数と、PDF原本未取得や未確認ルールの状態を各列に分離。
- `data/competitions/2026/hiroshima_eight_district_official_macro_comparison_2026.csv`：8季節地区の一次枠・その他枠・免除・季節合計と、出版社側イベント件数の比較。
- `phase2_engine/hiroshima_stage13e3g27.py`：Stage24/26監査への回帰、史実2026春秋各32枠、primary38＋二位校35＋追加決定14、出典年度・名前・Drive file mapping、未承認routeの誤解除をfail-closed検査。
- `tests/test_stage13e3g27_hiroshima_eight_official_previews.py`：ソース差替・年度誤記・根拠偽装・免除二重計上・公式未確認の全矢印/年次汎用FMT025 release詐称を拒否。
- `data/research/2026/research_pending_queue.csv`：RS2026026の進捗を追記し、`design_pending`は維持。

Stage23の`drive_html_loading_only`は当時の履歴スナップショットとして変更しない。今回の画像アクセス確認は別CSVで表現し、Stage24/25秋西の履歴も変更しない。

## Stage 28の候補

1. 各公式画像の可読範囲から**公式試合番号＋勝敗の進行矢印**を地区ごとに1つずつ独立証拠台帳へ転記し、学校・試合日別の二次結果と照合する。高解像度PDFを取得できない箇所は未確認にとどめる。
2. 秋西2026の年別DAGから可変参加校数・可変敗者移動を設計する際は、2027年の仮想学校IDと別々に保持し、必要な資料がない未来年は独立Sandboxのみ。
3. 本番FMT025や代表決定後の任意順位戦は、公式経路と追加開催の意義が確認できるまでは変更しない。

**Stage27の達成基準**：高野連公式図8/8の大枠閲覧、既存8地区の枠・一次ゾーン構造と出版社イベントを区別した監査・回帰テスト。公式8地区全試合の抽選DAG全矢印の完全復元ではない。
