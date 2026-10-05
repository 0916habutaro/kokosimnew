# Stage 12G 九州・沖縄8県 春秋県大会日程 調査報告書

作成日: 2026-10-06  
対象年度: 2026年度  
対象地域: 九州・沖縄  
対象県: 福岡・佐賀・長崎・熊本・大分・宮崎・鹿児島・沖縄

## 1. 調査目的

Stage 12Gとして九州・沖縄8県の春秋16大会について、既存Stage 12B〜12Cで確定したBRANCH_QUALIFIER・SEED_EVENT・MAINの境界と整合させ、県大会MAINの日程を構造化する。

## 2. 完了結果

- 対象大会: 16大会
- competition_id解決: 16/16
- master反映: 16/16
- 構造化試合日: 180日
- 16大会すべて research_status=complete
- 16大会すべて calendar_status=official_schedule
- 県春秋94大会全体: official_schedule 93 / research_pending 1
- Stage 12G累計試合日: 794日
- 残件: 東京都春 CMP000094 のみ

## 3. 大会別日数

| 県 | 春 | 秋 | 合計 | 主な境界判断 |
|---|---:|---:|---:|---|
| 福岡 | 3 | 6 | 9 | 北部・南部BRANCH_QUALIFIERを除外 |
| 佐賀 | 10 | 13 | 23 | 県内一括MAIN |
| 長崎 | 8 | 12 | 20 | 地区会長杯等は別大会 |
| 熊本 | 11 | 18 | 29 | 県内一括MAIN |
| 大分 | 11 | 13 | 24 | 4支部別大会を除外。秋の継続試合を公式速報優先で整理 |
| 宮崎 | 11 | 12 | 23 | 秋新人3地区大会はSEED_EVENT |
| 鹿児島 | 13 | 16 | 29 | 秋7地区大会はSEED_EVENT |
| 沖縄 | 11 | 12 | 23 | 秋新人中央大会はSEED_EVENT |
| **合計** | **78** | **102** | **180** | |

## 4. 重要な判断

### 福岡

春・秋とも大会データ上は北部・南部の段階を含む大規模トーナメントとして表示されるが、既存Stage 12Bでは地区段階をBRANCH_QUALIFIERとして機械構造化済み。したがってStage 12GのMAIN日程は、春は8校による4/2準々決勝〜4/6決勝、秋は16校段階が始まる10/3以降だけを登録した。

### 大分秋

大分県高野連公式速報を優先した。9/27は試合が途中で特別継続試合となり完了試合がなく、9/28は全試合中止、9/29も開始試合が途中で継続試合となり完了試合がない。これら3日はMAINの完了試合日から除外し、3試合が完了した9/30を採用した。

一部二次大会データでは継続試合が開始日に紐付く表示があるが、Stage 12Gではこれまでと同様に公式速報による「試合が完了した日」を基準とする。

### 宮崎・鹿児島・沖縄の秋

- 宮崎: 新人3地区大会は8シード校を決めるSEED_EVENT
- 鹿児島: 秋季7地区大会は県予選の8シード校を決めるSEED_EVENT
- 沖縄: 地区新人予選・新人中央大会は秋季県大会シード決定用SEED_EVENT

いずれも県大会参加資格を絞るBRANCH_QUALIFIERではないため、Stage 12G MAIN日程には含めない。

### 将来日程

2026-10-06時点で未実施の秋季日程は予定日として登録している。主な再照合対象は福岡10/6・7・10・12、佐賀10/10・12、長崎10/10・12、大分10/10・11、鹿児島10/10・11、沖縄10/10。大会終了後に実績日を再確認する。

## 5. 主な調査資料

- 福岡春: https://www.hb-nippon.com/tournaments/1172
- 福岡秋: https://www.hb-nippon.com/tournaments/1878
- 佐賀春: https://www.hb-nippon.com/tournaments/1170
- 佐賀秋: https://www.hb-nippon.com/tournaments/1951
- 長崎春: https://www.hb-nippon.com/tournaments/1187
- 長崎秋: https://www.hb-nippon.com/tournaments/1955
- 熊本春: https://www.hb-nippon.com/tournaments/1177
- 熊本秋: https://www.hb-nippon.com/tournaments/1950
- 大分春: https://www.hb-nippon.com/tournaments/1169
- 大分秋公式速報: https://www.oita-kouyaren.com/news/news_1.html
- 宮崎春: https://www.hb-nippon.com/tournaments/1176
- 宮崎秋: https://miyazaki-hbf.jp/schedule/3
- 鹿児島春: https://www.hb-nippon.com/tournaments/1182
- 鹿児島秋: https://www.hb-nippon.com/tournaments/1967
- 沖縄春: https://www.hb-nippon.com/tournaments/1168
- 沖縄秋公式: https://www.kouyaren-okinawa.jp/

## 6. 検証結果

GitHub Actions上で実際に検証を実行し、以下を確認した。

- unit test: **116 / 116 PASS**
- Stage 12G九州・沖縄validation: **15 / 15 PASS**
- season E2E県大会: **94 / 94 PASS**
- `prefectural_calendar_gap_count = 1`
- warnings: **0**

実行ログでは `Ran 116 tests ... OK`、`PREFECTURAL_PASS=94`、`PREFECTURAL_TOTAL=94`、`CALENDAR_GAPS=1`、`WARNINGS=[]` を確認した。

## 7. 次工程

Stage 12G最終残件である東京都春 CMP000094 を個別調査・登録し、県春秋94大会のカレンダーを完結させる。
