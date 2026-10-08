# Stage 13E-3F-3 千葉県春季8地区予選の実試合日調査

調査日：2026-10-08

対象：CMP000092 / SC2026016 / STG000175（BRANCH_QUALIFIER）

## 調査対象・判定規則

2026年（令和8年度）第79回春季千葉県高等学校野球大会予選の第1～第8地区の試合結果を照合した。大会全体の会期は4月2日～8日だが、ゲームへの登録は会期全日ではなく「当日に個別の対戦結果がある日」の重複なしunionとする。

採用日（4日）：

2026-04-02;2026-04-04;2026-04-05;2026-04-08

除外：
- 4月3日・6日・7日：県高野連公式「令和8年度行事予定」で春季予選の開催対象日から明示的に除外されており、8地区の大会試合結果の日付にも現れない。
- 4月18日以降：県大会MAINに該当し、pre-MAIN BRANCH_QUALIFIERには含めない。
- 不戦勝・未設定カードのみの日付：単独の実試合日根拠にしない（第6地区の「成田北不戦勝」など）。

## 根拠（一次資料）

- 千葉県高野連 2026年度行事予定： https://chbf.or.jp/calendar-20261-20273
  - 4月2日～8日（3・6・7日を除く）と明記。
- 千葉県高野連 春季県大会予選案内（2026年4月8日更新）：
  https://chbf.or.jp/archives/oshirase2/令和８年度第７９回春季千葉県高等学校野球大会
- 千葉県高野連 4月8日付・地区予選公式結果PDF：
  https://chbf.or.jp/wp-content/uploads/2026/04/R８春季地区予選（４月８日）.pdf
  - 8ページに第1～第8地区の確定組合せ・結果を掲載。

## 補助照合（個別試合日・地区別の結果一覧）

- 第1地区：https://www.hb-nippon.com/tournaments/1153
- 第2地区：https://www.hb-nippon.com/tournaments/1154
- 第3地区：https://www.hb-nippon.com/tournaments/1155
- 第4地区：https://www.hb-nippon.com/tournaments/1156
- 第5地区：https://www.hb-nippon.com/tournaments/1157
- 第6地区：https://www.hb-nippon.com/tournaments/1158
- 第7地区：https://www.hb-nippon.com/tournaments/1159
- 第8地区：https://www.hb-nippon.com/tournaments/1160
- 県大会MAIN（参考、予選には含めない）：https://chbf.or.jp/archives/oshirase2/令和８年度第７９回春季千葉県高等学校野球大会-2

## データ処理

SC2026016 の `date_status` を `verified` に更新し、`calendar_relation=explicitly_excluded_from_main_calendar` を維持。調査台帳 RS2026008 を `resolved` とした。ほかの research_pending の大会は変更しない。

この記録は実在の全試合カードや個々の試合結果をゲームへ取り込むものではなく、予選ステージの日付集合だけを構造化したものである。
