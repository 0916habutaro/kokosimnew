# Stage 12G 関東7県 春秋県大会日程 調査報告書

作成日: 2026-10-05  
対象年度: 2026年度  
対象地域: 関東（東京都を除く）  
対象都県: 茨城・栃木・群馬・埼玉・千葉・神奈川・山梨

## 1. 調査目的

Stage 12Gでは、全国の春季・秋季県大会について、ゲーム内で使用できる形に開催期間と実試合日を構造化する。

本報告書では、関東地区のうち東京都を除く7県について、春秋14大会の県大会本体の日程を確定し、`season_calendar.csv` と試合日明細へ反映した判断根拠を記録する。

## 2. 完了結果

- 対象大会: 14大会
- competition_id解決: 14/14
- master反映: 14/14
- 構造化した試合日: 133日
- 関東14大会のresearch_status: すべて `complete`
- 関東14大会のcalendar_status: すべて `official_schedule`
- 県春秋94大会全体: `official_schedule 29 / research_pending 65`
- unit test: 80/80 PASS
- season E2E県大会: 94/94 PASS
- warnings: 0

## 3. 日程採用ルール

今回のStage 12Gでは、次の基準で日程を登録した。

1. 県大会本体（MAIN）で実際に試合が行われた日を `match_dates` とする。
2. 地区予選・支部予選など、県大会本体より前の大会は原則として除外する。
3. 予備日のみの日付は除外する。
4. 雨天中止で試合が行われなかった日は除外し、順延後に実際に試合が行われた日を採用する。
5. 継続試合のみ・中止のみで、その日に「完了試合」が存在しない場合は、今回の試合日集計から除外する。
6. 公式資料と県高野連が利用する公式データ協力先の情報を優先し、必要に応じて公開大会結果を照合する。
7. 2026-10-05時点で未実施だが公式に確定している将来日程については、実績日と混同しないよう注記を付けて登録する。

## 4. 14大会の確定内容

| 県 | 季節 | competition_id | 大会名 | 開始日 | 終了日 | 試合日数 | 主な判断 |
|---|---|---|---|---|---|---:|---|
| 茨城 | 春 | CMP000084 | 第78回春季関東地区高等学校野球茨城県大会 | 4/18 | 5/4 | 9 | 地区予選を除外し県大会本体のみ採用 |
| 茨城 | 秋 | CMP000085 | 第79回秋季関東地区高等学校野球茨城県大会 | 9/19 | 10/4 | 9 | 9/20は完了試合なしのため除外 |
| 栃木 | 春 | CMP000086 | 第79回春季栃木県高等学校野球大会 | 4/11 | 5/3 | 9 | 大会要項の9日間と実施日が一致 |
| 栃木 | 秋 | CMP000087 | 第79回秋季栃木県高等学校野球大会 | 9/12 | 10/4 | 12 | 県大会本体の完了試合日を採用 |
| 群馬 | 春 | CMP000088 | 第78回春季関東地区高等学校野球大会 群馬県予選 | 4/11 | 5/3 | 11 | 県予選本体の完了試合日を採用 |
| 群馬 | 秋 | CMP000089 | 第79回秋季関東地区高等学校野球大会 群馬県予選 | 9/5 | 9/29 | 11 | 9/26・9/28の全試合中止を除外し順延日を採用 |
| 埼玉 | 春 | CMP000090 | 令和8年度 春季埼玉県高等学校野球大会 | 4/23 | 5/5 | 8 | 地区予選を除外 |
| 埼玉 | 秋 | CMP000091 | 令和8年度 秋季埼玉県高等学校野球大会 | 9/25 | 10/6 | 7 | 10/6決勝は10/5調査時点の公式予定日 |
| 千葉 | 春 | CMP000092 | 令和8年度 第79回春季千葉県高等学校野球大会 | 4/18 | 5/3 | 6 | 地区予選を除外 |
| 千葉 | 秋 | CMP000093 | 令和8年度 第79回秋季千葉県高等学校野球大会 | 9/19 | 10/5 | 9 | 複数の雨天順延を実施日へ正規化 |
| 神奈川 | 春 | CMP000095 | 令和8年度 神奈川県高等学校野球春季大会 | 4/4 | 5/3 | 9 | 県高野連公式結果で決勝5/3まで確認 |
| 神奈川 | 秋 | CMP000096 | 令和8年度 神奈川県高等学校野球秋季大会 | 9/5 | 10/1 | 10 | 県高野連公式結果と大会終了記事を照合 |
| 山梨 | 春 | CMP000105 | 第78回春季関東地区高等学校野球山梨県大会 | 4/11 | 5/6 | 11 | 大会表示は5/7までだが最終完了試合は5/6 |
| 山梨 | 秋 | CMP000106 | 第79回秋季関東地区高等学校野球山梨県大会 | 9/5 | 10/4 | 12 | 継続試合日・中止日を完了試合日の集計から分離 |

## 5. 県別の調査判断

### 茨城県

春は県高野連公式試合情報を主資料とし、公開大会結果で試合日を照合した。地区予選は県大会本体の `match_dates` から除外した。

秋は県大会の日程・結果を公式データ協力先で確認した。9月20日は当初日程に関連する日付だが、完了試合がないため採用せず、順延後に試合が完了した日を登録した。

### 栃木県

春は大会要項上の9日間と試合結果の日付が一致したため、その9日を採用した。予備日は登録していない。

秋は公式データ協力先の県大会日程・結果を基準に、県大会本体の完了試合日を採用した。

### 群馬県

春は県予選本体の完了試合日を採用した。

秋は雨天中止の影響が大きいため、中止日と順延後の実施日を明示的に分離した。9月26日の準決勝は全試合中止となり9月27日に順延、9月28日の決勝・3位決定戦も中止となり9月29日に順延された。このため9月26日・28日は `match_dates` から除外し、9月27日・29日を採用した。

### 埼玉県

春は地区予選を除外し、県大会本体のみを登録した。

秋は2026年10月5日時点で準決勝まで終了しており、10月6日の決勝が公式トーナメント上で予定されている。この10月6日は調査時点では「実施済み」ではなく「公式に確定した将来予定日」であるため、その旨を監査CSVと `season_calendar.csv` のnotesへ残している。

この大会については、10月6日終了後に実績確認を行い、順延等が発生した場合は更新対象となる。

### 千葉県

春は県大会本体のみを採用し、地区予選は除外した。

秋は雨天順延を反映した。9月20日・26日は全試合順延、9月29日・30日も対象試合が順延されたため、実際に試合が行われた日へ正規化した。9月28日は2試合が実施されているため採用した。

### 神奈川県

春は県高野連公式結果ページを日付単位で確認し、4月4日から5月3日の決勝までを構造化した。地区予選は除外した。

秋は県高野連公式結果ページに加え、10月1日の大会終了記事も照合し、9月5日から10月1日までの実施日を採用した。

### 山梨県

春は大会ページ上の表示期間が5月7日までとなっているが、完了試合の最終日は5月6日であるため、5月7日は試合日から除外した。

秋は継続試合・中止の扱いを分離した。9月8日の継続試合日、9月9日の中止日、9月26日の継続・中止日は「完了試合日」の集計には含めず、完了した試合が存在する日を `match_dates` とした。

## 6. 主な調査資料

### 茨城
- 春: https://www.ibaraki-hbf.com/schedule?gamedate=20260502&section=2
- 秋: https://baseball.omyutech.com/CupHomePageMain.action?cupId=20260002415

### 栃木
- 春: https://baseball.omyutech.com/CupHomePageMain.action?cupId=20260007203
- 秋: https://baseball.omyutech.com/CupHomePageMain.action?cupId=20260000766

### 群馬
- 春: https://baseball.omyutech.com/CupHomePageMain.action?cupId=20260007202
- 秋: https://baseball.omyutech.com/CupHomePageMain.action?cupId=20260000167

### 埼玉
- 春: https://baseball.omyutech.com/CupHomePageMain.action?cupId=20260009418
- 秋: https://baseball.omyutech.com/CupHomePageMain.action?cupId=20260000502
- 秋補助資料: https://saitama-baseball.com/akikentai2026/

### 千葉
- 春: https://baseball.omyutech.com/leagueCup.action?leagueId=212
- 秋: https://chbf.or.jp/

### 神奈川
- 春: https://kanagawa-hbf.sakura.ne.jp/2026/?result-hard_=prefecture-spring
- 秋: https://kanagawa-hbf.sakura.ne.jp/2026/?result-hard_=prefecture-autumn

### 山梨
- 春: https://baseball.omyutech.com/CupHomePageMain.action?cupId=20260007204
- 秋: https://baseball.omyutech.com/CupHomePageMain.action?cupId=20260000331

詳細な主資料・補助資料・判断理由は `audits/phase2/stage12g/stage12g_kanto_schedule_audit_20261005.csv` を正とする。

## 7. 今回更新した主要ファイル

- `data/schedules/2026/season_calendar.csv`
- `data/schedules/2026/stage12g_kanto_match_days_20261005.csv`
- `data/sources/phase2_sources.csv`
- `audits/phase2/stage12g/stage12g_kanto_schedule_audit_20261005.csv`
- `audits/phase2/stage12g/stage12g_kanto_validation_20261005.csv`
- `audits/phase2/stage12g/stage12g_kanto_test_summary_20261005.csv`
- `tests/test_stage12g_kanto_schedule.py`
- `tests/test_stage12d_season_engine.py`
- `tests/test_stage12g_tohoku_schedule.py`

## 8. 検証結果

`stage12g_kanto_validation_20261005.csv` の検証はすべてPASS。

主な確認事項:

- 14大会すべてcompetition_id解決済み
- 14大会すべてmasterへmerge済み
- 133試合日すべてcompetition_idあり
- 14大会すべてsource_idが `phase2_sources.csv` に存在
- 県春秋94大会のうち29大会が `official_schedule`
- 未確定は65大会
- unit test 80/80 PASS
- season E2E県大会 94/94 PASS
- warnings 0

## 9. 残課題

埼玉県秋季大会の10月6日決勝は、本報告書作成時点（2026-10-05）では未来の公式予定日である。

10月6日の大会終了後、実施日が予定どおりだったかを確認する。雨天順延等があった場合は、`season_calendar.csv`、match-days、audit、本報告書を実績ベースへ更新する。

Stage 12Gの次工程は、北信越5県（新潟・富山・石川・福井・長野）の春秋10大会の日程構造化とする。
