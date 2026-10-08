# Stage 13E-3G-7：2026広島春秋4地区・代表決定経路の構造監査

実施日：2026-10-09

## 結論と監査範囲

広島県の2026年春季・秋季地区予選では「1位校」「2位校」「代表・順位決定戦」の大会名が、県大会出場枠を獲得するための**予選経路**として使われている。単に「順位」の語があるだけで、出場権の確定した学校同士が行う任意順位戦とは判定できない。

県高野連の公式サイトには春秋とも**県大会出場32校**と、4地区の大会結果表へのリンクがある。秋季の地区別枠は**西部7・北部6・南部10・東部9**。既存ゲームの春季stage-group設定では**西部7・北部7・南部9・東部9**と合計32枠を保持している。春季の地区別内訳は今回の県高野連公開テキストには直接明記されておらず、**既存ゲーム登録値として監査**したもので「今回新たに公式確定した枠数」とは区別する。

公式：
- [広島県高野連・令和8年度春秋大会の公式要項・4地区組合せリンク](https://hiroshima.hhbf1950.or.jp/大会関連/硬式部各種大会)
- [2026春季地区予選のサブ大会一覧（連盟主管試合速報：SportsOnline）](https://www.sportsonline.jp/reportv2/PublisherFull/Rally.aspx?parentid=RX_ZV)
- [2026秋季地区予選のサブ大会一覧（連盟大会試合速報：SportsOnline）](https://www.sportsonline.jp/reportv2/PublisherFull/Rally.aspx?ParentID=RX%5DSZ)

## 地区別の代表選出経路

| シーズン | 西部 | 北部 | 南部 | 東部 | 予選サブ大会総数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 春季 | 9 | 10 | 15 | 9 | **43** |
| 秋季 | 9 | 10 | 16 | 9 | **44** |
| **計** | 18 | 20 | 31 | 18 | **87** |

この「87」は**サブ大会（ゾーン別1位校・2位校決定経路＋最終代表決定経路）の数**。個別の試合数、試合日数、非blocking順位決定戦の数ではない。SportsOnline一覧は春季44件・秋季45件だが、それぞれ**県大会MAINを1件含む**ため、43件と44件を地区予選経路として分離した。

`data/competitions/2026/hiroshima_district_qualification_routes.csv`には、正式な`competition_id`・`stage_group_id`・地域・サブ大会名・初日/終了日・分類・出典を登録。

- `first_place_berth_path`：ゾーン1位校を選ぶ勝ち上がり経路。
- `second_place_berth_path`：ゾーン敗者復活・2位校決定への経路。
- `cross_zone_berth_decider`：複数ゾーンの2位校同士などによる最終県大会出場権決定戦。

すべて`qualification_effect=qualification_sensitive`、`verification_scope=bracket_level_only`とする。これは各経路が**県大会進出に関係する**という意味であり、その経路に含まれる**すべての試合が、出場権未確定校同士の対戦だと個別に証明したものではない**。

## 学校別・試合別に確認した事例

`hiroshima_qualification_examples.csv`に9試合を登録。確認できる代表決定結果は次のとおり。

| シーズン | 地区 | 日付 | 対戦結果と資格 |
| --- | --- | --- | --- |
| 春 | 西部 | 4/11 | 広島城北5-3山陽、県大会最後の出場枠 |
| 秋 | 西部 | 8/29 | 広島商11-1宮島工、山陽6-0基町 |
| 秋 | 東部 | 8/29・9/5 | 福山10-1府中、神辺旭5-0英数学館 |
| 秋 | 北部 | 8/23 | 広島新庄12-2可部、高陽東6-2三次 |
| 秋 | 南部 | 9/5 | 瀬戸内4-3熊野、広島桜が丘9-4呉三津田 |

前工程から登録済み`RR20260032`・`RR20260033`・`RR20260034`の3件は、追加順位戦への混入禁止を維持する。記事による県大会切符獲得校の時系列照合：
- [2026春3/28の地区予選](https://www.hb-nippon.com/articles/12011)
- [2026春4/5の代表決定戦](https://www.hb-nippon.com/articles/12227)
- [2026春4/11 広島城北が最後の出場枠](https://www.hb-nippon.com/articles/12356)
- [2026秋8/23の初期代表決定](https://www.hb-nippon.com/articles/16625)
- [2026秋8/29の代表決定](https://www.hb-nippon.com/articles/16739)
- [2026秋8/30の敗者復活](https://www.hb-nippon.com/articles/16781)
- [2026秋9/5の敗者復活代表決定](https://www.hb-nippon.com/articles/16879)

## 実装

- `phase2_engine/hiroshima_district_qualification_2026.py`にルート単位の独立監査`audit_2026_hiroshima_qualification_routes()`を追加。
- 地区season8区分、サブ大会87件のユニークさ、全stage groupの地区一致、各経路の分類、開催期間、一次リンクを検証する。
- 秋季県大会の連盟公表の出場32枠（西7・北6・南10・東9）を検証し、春季は既存stage group合計32枠を維持する。
- 具体的な9試合の日時、勝敗、勝者、既知の代表決定戦3件との参照一致を検証。
- 既存`hiroshima_2026_qualification_guard()`にこのルート監査を接続し、地区大会名に「一位」「二位」「順位」が現れたときに自動でnonblocking順位戦を作るような誤操作を防ぐ。
- 全工程の既存`CompetitionRun`・県大会MAIN出場校・年間依存関係・既存SQLiteセーブ構造を変更しない。

## 残存事項・完了判定

**本工程で春秋4地区のサブ大会「経路一覧」まで完了**。しかし、公式のGoogle Drive提供地区予選PDF10件（秋全地区＋4地区、春全地区＋4地区）の**対戦校ごとの全試合について、県大会出場権が当該試合直前に既に確定していたか**までは全件照合していない。このため、**「追加順位戦が存在しない」と断定しない**。

`RS2026026`（FMT025）は`design_pending`として維持する。翌工程では公式PDFの詳細照合、特に1位・2位校決定の途中で**双方が既に出場資格を持つカードが存在したか**を試合単位で監査する。確認できない限り広島由来の非blocking順位戦を登録しない。

`RS2026025`（FMT022）も本工程とは独立して保留を維持。2026明治神宮大会の公開待ち`RS2026022`は変更しない。

## 再現方法

```bash
python -m unittest tests.test_stage13e3g7_hiroshima_qualification_routes -v
python -m unittest discover -s tests -p 'test_*.py' -v
```
