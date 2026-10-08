# Stage 13E-3G-8：広島2026春秋4地区・公式PDFリンクと個別試合の中間監査

実施日：2026-10-09

## 判定

**全公式PDFを試合単位で照合したとの主張はしない。FMT025は設計保留を継続。**

広島県高野連公式サイトに春秋各4地区のPDFリンクを確認した。ただしGoogle Driveで公開されたPDFの**本文はこの工程で取得・解析できなかった**。その代わり、連盟主管のSportsOnlineの43＋44予選経路と、日付・学校・スコアを掲載する「令和高校野球」等の試合別掲載を照合し、**8地区季節各1件、計8件の具体的資格決定戦**を独立したアンカーとして登録した。この8件は「全試合」ではない。

公式ハブ：[広島県高等学校野球連盟 2026春秋大会](https://hiroshima.hhbf1950.or.jp/大会関連/硬式部各種大会)

## 公式地区別PDFリンク8件

| 季節 | 地区 | 高野連公式サイトからのリンク | 日付付き試合結果の補助資料 | PDF本文監査 |
| --- | --- | --- | --- | --- |
| 春 | 西部 | [公式組合せ](https://drive.google.com/file/d/1H3_Nxm9VjTBdM-cgVWmX0X9v3CiDNkMr/view?usp=sharing) | [対戦結果](https://www.reiwa-hb-sch-and-res-gatr-fod.com/hiroshima/2026spring/west-area/) | 未実施 |
| 春 | 北部 | [公式組合せ](https://drive.google.com/file/d/1vKI_4AFyxkvlFw-ZaJ6TMKBDXpPYeyFz/view?usp=sharing) | [対戦結果](https://www.reiwa-hb-sch-and-res-gatr-fod.com/hiroshima/2026spring/north-area/) | 未実施 |
| 春 | 南部 | [公式組合せ](https://drive.google.com/file/d/1gSVMVuzfjIEgklHdTgXi8eqj0OUloPS_/view?usp=sharing) | [対戦結果](https://www.reiwa-hb-sch-and-res-gatr-fod.com/hiroshima/2026spring/south-area/) | 未実施 |
| 春 | 東部 | [公式組合せ](https://drive.google.com/file/d/1Su5If9rOmkfLvMLuUiPjBpbOhkd27qPT/view?usp=sharing) | [対戦結果](https://www.reiwa-hb-sch-and-res-gatr-fod.com/hiroshima/2026spring/east-area/) | 未実施 |
| 秋 | 西部 | [公式組合せ](https://drive.google.com/file/d/1VxVW_r_L5MwnP3hkqZToGe3o5StK5NQ-/view?usp=sharing) | [対戦結果](https://www.reiwa-hb-sch-and-res-gatr-fod.com/hiroshima/2026autumn/west-area/) | 未実施 |
| 秋 | 北部 | [公式組合せ](https://drive.google.com/file/d/11nILxjp_0ghyw-ir8u3EjeKXHBL_mpQh/view?usp=sharing) | [対戦結果](https://www.reiwa-hb-sch-and-res-gatr-fod.com/hiroshima/2026autumn/north-area/) | 未実施 |
| 秋 | 南部 | [公式組合せ](https://drive.google.com/file/d/1rdH-iz4Gqc4jJLPHoPrpJlST6dfZoxfO/view?usp=sharing) | [対戦結果](https://www.reiwa-hb-sch-and-res-gatr-fod.com/hiroshima/2026autumn/south-area/) | 未実施 |
| 秋 | 東部 | [公式組合せ](https://drive.google.com/file/d/1pfsrSTuhiH5_pmPvyvCBObonztTF4dd0/view?usp=sharing) | [対戦結果](https://www.reiwa-hb-sch-and-res-gatr-fod.com/hiroshima/2026autumn/east-area/) | 未実施 |

データ：`data/competitions/2026/hiroshima_bracket_pdf_review_2026.csv`。公式リンクの所在確認とPDF本文読取の状態を分離し、リンクだけで「全カード精査済み」とは認定しない。

## 試合単位で追加した資格決定戦アンカー

| 春秋 | 地区 | 日付 | 確認した対戦と結果 | 分類 |
| --- | --- | --- | --- | --- |
| 春 | 西部 | 4/11 | 広島城北5-3山陽 | 県大会最後の出場権決定 |
| 春 | 北部 | 3/29 | 高陽東2-1安西 | 敗者戦代表決定 |
| 春 | 南部 | 4/5 | 広島市工4-3広島桜が丘 | 敗者戦代表決定 |
| 春 | 東部 | 3/29 | 近大福山13-4尾道東 | 敗者戦代表決定 |
| 秋 | 西部 | 8/30 | 広島井口6-2宮島工 | 敗者戦代表決定 |
| 秋 | 北部 | 8/30 | 三次9-3上下 | 敗者戦代表決定 |
| 秋 | 南部 | 9/6 | 熊野10-4安芸府中 | 敗者戦代表決定 |
| 秋 | 東部 | 9/5 | 神辺旭5-0英数学館 | 敗者戦代表決定 |

データ：`data/competitions/2026/hiroshima_match_level_anchors_2026.csv`。前工程9件との重複2件（春西・秋東）、合算ユニークな**資格決定戦の具体例15件**。いずれも資格が確定している二校間の任意順位戦として登録しない。

特に秋南部では9/5瀬戸内4-3熊野のあと、熊野は9/6安芸府中に10-4で勝利して進出した。9/5の敗北で終わりではない資格選出経路の存在を確認したため、タイトルだけによる決定的な誤分類を避ける必要がある。

## 実装と残存監査

`phase2_engine/hiroshima_match_level_2026.py`：8公式PDFの異なるID、地区stage group対応、ソース出典、8試合の日時・対戦・勝敗、前工程例との2試合一致を監査。**PDF未読と全試合未完了を明示的に検証し、これを「済」に書き換える誤更新を失敗扱い**とする。2026広島のFMT025解放は常に不許可（明示的設計変更が必要）。`tests/test_stage13e3g8_hiroshima_match_level.py`に回帰テストを追加。

本工程で未達：春秋4地区の公式PDFを直接読み、全カードの試合日時・二校の資格ロック時点・敗者復活経路を突合する作業。地区全カードを監査するまでは「順位戦なし」も「順位戦あり」も断定しない。研究台帳`RS2026026`は`design_pending`のまま、既存のFMT022も無変更。

### 継続時の解除条件

1. 公式PDF8件を直接取得・閲覧し、両校・各試合の勝敗と日付を記録する。
2. 地区ごとに県大会32枠の通過校と各校の**資格確定イベント・時刻**を追跡する。
3. 全地区で公式PDFの掲載試合数と構造化試合数が一致することを検証する。
4. 両校とも当該試合前に資格がロック済みの実試合のみを、独立した`FMT025`候補として提案する。保留解除には専用レビューが必要。

既存の大会エンジン・県MAIN進出校・セーブ構造は変更しない。
