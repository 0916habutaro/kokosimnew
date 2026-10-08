# Stage 13E-3F-3 北海道春季10支部予選の実試合日調査

調査日：2026-10-08

対象：CMP000004 / SC2026001 / STG000163（BRANCH_QUALIFIER）

## 調査対象と登録方針

2026年度第65回春季北海道高等学校野球大会の支部予選について、**北海道高等学校野球連盟の公式硬式速報を5月8日～17日の全10日分照合**した。

調査対象の10支部は **函館、室蘭、札幌、小樽、空知、旭川、名寄、北見、十勝、釧根**。日によって開催支部は異なり、全支部が10日連続で試合をしたという意味ではない。各日の「本日行われた試合」欄で、少なくとも一つの支部に **プレーボール・ゲームセット・両校の得点** が存在することを確認し、北海道全体の実試合日を重複のない集合（union）にした。

## 採用日（10日）

```text
2026-05-08;2026-05-09;2026-05-10;2026-05-11;2026-05-12;2026-05-13;2026-05-14;2026-05-15;2026-05-16;2026-05-17
```

| 日付 | 判定 | 一次資料 |
| --- | --- | --- |
| 5月8日 | 採用：道高野連公式の試合結果（得点・勝敗）あり | [日別結果](https://www.hokkaido-hbf.jp/hp/newsflash_1_20260508.html) |
| 5月9日 | 採用：道高野連公式の試合結果（得点・勝敗）あり | [日別結果](https://www.hokkaido-hbf.jp/hp/newsflash_1_20260509.html) |
| 5月10日 | 採用：道高野連公式の試合結果（得点・勝敗）あり | [日別結果](https://www.hokkaido-hbf.jp/hp/newsflash_1_20260510.html) |
| 5月11日 | 採用：道高野連公式の試合結果（得点・勝敗）あり | [日別結果](https://www.hokkaido-hbf.jp/hp/newsflash_1_20260511.html) |
| 5月12日 | 採用：道高野連公式の試合結果（得点・勝敗）あり | [日別結果](https://www.hokkaido-hbf.jp/hp/newsflash_1_20260512.html) |
| 5月13日 | 採用：道高野連公式の試合結果（得点・勝敗）あり | [日別結果](https://www.hokkaido-hbf.jp/hp/newsflash_1_20260513.html) |
| 5月14日 | 採用：道高野連公式の試合結果（得点・勝敗）あり | [日別結果](https://www.hokkaido-hbf.jp/hp/newsflash_1_20260514.html) |
| 5月15日 | 採用：道高野連公式の試合結果（得点・勝敗）あり | [日別結果](https://www.hokkaido-hbf.jp/hp/newsflash_1_20260515.html) |
| 5月16日 | 採用：道高野連公式の試合結果（得点・勝敗）あり | [日別結果](https://www.hokkaido-hbf.jp/hp/newsflash_1_20260516.html) |
| 5月17日 | 採用：道高野連公式の試合結果（得点・勝敗）あり | [日別結果](https://www.hokkaido-hbf.jp/hp/newsflash_1_20260517.html) |

主な照合点：
- **5月8日**：旭川支部の旭川永嶺3-2旭川龍谷、富良野12-1旭川南で支部予選開幕を確認
- **5月9日**：函館・室蘭・札幌・空知・十勝などで結果あり（札幌は天候による継続試合もあるが、ほかに完了試合もあるため採用）
- **5月12日**：函館・室蘭・札幌・小樽・空知・旭川・北見・十勝・釧根などで実試合あり
- **5月14日**：札幌・小樽・名寄・釧根の各支部で実試合あり
- **5月15日**：室蘭・札幌・旭川の各支部で実試合あり
- **5月16日**：10支部で試合結果あり。室蘭支部決勝も同日
- **5月17日**：函館・札幌・小樽・空知・旭川・名寄・北見・十勝・釧根の試合結果。道高野連公式速報の春季支部予選最終掲載日
- **5月18日以降**：支部予選の追加実試合として確認されていない。会期の推測や未消化予定だけでは追加しない

## 公式日別結果（一次資料）

北海道高等学校野球連盟「令和8年度 春季北海道高等学校野球大会 硬式速報」：

- https://www.hokkaido-hbf.jp/hp/newsflash_1_20260508.html
- https://www.hokkaido-hbf.jp/hp/newsflash_1_20260509.html
- https://www.hokkaido-hbf.jp/hp/newsflash_1_20260510.html
- https://www.hokkaido-hbf.jp/hp/newsflash_1_20260511.html
- https://www.hokkaido-hbf.jp/hp/newsflash_1_20260512.html
- https://www.hokkaido-hbf.jp/hp/newsflash_1_20260513.html
- https://www.hokkaido-hbf.jp/hp/newsflash_1_20260514.html
- https://www.hokkaido-hbf.jp/hp/newsflash_1_20260515.html
- https://www.hokkaido-hbf.jp/hp/newsflash_1_20260516.html
- https://www.hokkaido-hbf.jp/hp/newsflash_1_20260517.html

補助資料：
- 北海道高野連の支部別「お知らせ」・大会結果一覧：https://hokkaido-hbf.jp/hp/hbf_h_2_information.php
- 札幌支部結果：https://www.hb-nippon.com/tournaments/1425
- 旭川支部結果：https://www.hb-nippon.com/tournaments/1445
- 名寄支部結果：https://www.hb-nippon.com/tournaments/1419

## 県大会MAINと研究台帳の扱い

既存の `CAL000004` （道大会MAIN）は**5月25・26・27・28・30・31日**で、全10支部の `BRANCH_QUALIFIER` とは非重複。MAINのCSVは変更しない。

変更：
- `SC2026001`：`date_list` 10日、`date_status=verified`
- `RS2026001`：`status=needs_research` → `resolved`
- `calendar_relation=not_structured_separately` の既存方針を保持
- これをもって、2026年度pre-MAIN stage calendar の `research_pending` 50件中0件を目指す

**注意**：今回の変更は「試合が行われた日付集合」をゲームに登録するものであり、実際の対戦校やスコアを架空選手・架空試合へ転記するものではない。
