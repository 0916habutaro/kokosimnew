# Stage 13E-3F-3 神奈川県春季4地域地区予選 実試合日調査

調査日：2026-10-08

対象：CMP000095 / SC2026019 / STG000177（BRANCH_QUALIFIER）

## 調査範囲と判定方針

神奈川県高等学校野球連盟が公開した2026年度春季地区予選の4地域を照合した。

- 川崎・横浜北地区
- 横浜南・横須賀地区
- 湘南・西湘地区
- 北相地区

ゲームのstage calendarには大会会期や予定日ではなく、**実際の得点・勝敗が確定した試合日を重複なしで統合した日付集合**を記録する。公式の4地域PDF（いずれも3月28日時点の対戦表・結果を収録）および2026年の個別試合結果を突合し、以下の5日とした。

```text
2026-03-20;2026-03-21;2026-03-22;2026-03-27;2026-03-28
```

## 日付別根拠

| 日付 | 判定 | 根拠 |
| --- | --- | --- |
| 3月20日 | 採用 | 川崎・横浜北の桐光学園9-2浅野、湘南・西湘の平塚学園9-2七里ガ浜、北相の東海大相模17-0厚木北など実試合結果あり。 |
| 3月21日 | 採用 | 4地域ともリーグ戦の試合結果あり。横浜南・横須賀地区はこの日から開催。 |
| 3月22日 | 採用 | 4地域で結果あり。 |
| 3月23～25日 | 除外 | 4地域の公式日別対戦表・結果に実試合を確認できない。 |
| 3月26日 | 除外 | 4地域の公式対戦表で予定カードが「中止」とされており、3月27日へ順延。予定日を実試合日として扱わない。 |
| 3月27日 | 採用 | 4地域で順延試合を含む実試合結果あり。 |
| 3月28日 | 採用 | 川崎・横浜北の岸根23-2幸、湘南・西湘の藤沢翔陵8-2小田原北、北相の上溝南27-3伊勢原、横浜南・横須賀の松陽3-1桜丘などの実試合結果あり。 |
| 3月29日以降 | 除外 | 地区予選として確認できる結果は3月28日まで。4月4日以降の試合は県大会MAIN。 |

## 一次資料（2026年神奈川県高野連）

- [春季大会地区予選・4地域への入口](https://kanagawa-hbf.sakura.ne.jp/preliminary/令和８年度2026年春季大会地区予選/)
- [川崎・横浜北地区の確定対戦表（3月28日）](https://kanagawa-hbf.sakura.ne.jp/wp/wp-content/uploads/2026/03/R8kawasaki_yokohamakita0328.pdf)
- [横浜南・横須賀地区の確定対戦表（3月28日）](https://kanagawa-hbf.sakura.ne.jp/wp/wp-content/uploads/2026/03/R8haruyokohamaminami_yokosuka0328.pdf)
- [湘南・西湘地区の確定対戦表（3月28日）](https://kanagawa-hbf.sakura.ne.jp/wp/wp-content/uploads/2026/03/R8harushonan_seisho0328.pdf)
- [北相地区の確定対戦表（3月28日）](https://kanagawa-hbf.sakura.ne.jp/wp/wp-content/uploads/2026/03/R8hokuso0328.pdf)
- [県大会2026年度春季試合結果（MAINは4月4日以降）](https://kanagawa-hbf.sakura.ne.jp/2026/?result-hard_=prefecture-spring)

## 補助照合（個別の実試合結果）

- [高校野球ドットコム：2026年3月20日の試合](https://www.hb-nippon.com/calendar?date=2026-03-20)
- [同：3月21日の試合](https://www.hb-nippon.com/calendar?date=2026-03-21)
- [同：3月28日の試合](https://www.hb-nippon.com/calendar?date=2026-03-28)
- [北相地区G～I](https://www.hb-nippon.com/tournaments/1256)
- [横浜南・横須賀地区A～D](https://www.hb-nippon.com/tournaments/1245)

## 登録内容

SC2026019: `date_status=verified`、`date_list`を5日で確定。
`calendar_relation=explicitly_excluded_from_main_calendar`を維持し、既存MAINの試合日を変更しない。

RS2026010: `needs_research`から`resolved`へ更新。
他の研究保留行は変更せず保持。

**注意**：これはステージの試合実施日を構造化する変更であり、実在の試合スコア・対戦校をゲーム内に移植するものではない。
