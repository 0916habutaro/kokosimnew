# 2026年度開始時の前提データ（実在）

新規ゲーム（2026年4月1日開始）の最初の春季大会で必要になる、ゲーム開始前の実際の結果。方針は `docs/design/game_definition.md` §8。

ゲーム内で生成した結果ではないので、ゲームの記録（試合結果・戦績）とは混ぜない。春季大会の予選免除・シード・推薦を決めるための入力としてだけ使う。

## `prior_results.csv`

| 列 | 内容 |
|---|---|
| `record_id` | `ISR` + 6桁 |
| `kind` | `senbatsu_entrant`（2026年選抜の出場校）／`autumn_prefectural`（2025年秋の県大会）／`autumn_regional`（2025年秋の地区大会） |
| `rule_id` | 使う側のルール（`data/competitions/competition_access_rules.csv` の `access_rule_id`）。選抜の出場校は複数のルールで使うので空欄 |
| `source_year` | 結果の年 |
| `source_competition_name` | 大会名 |
| `prefecture_code` | 学校の都道府県 |
| `school_id` | `data/master/schools.csv` の学校ID |
| `published_team_name` | 出典に書かれた校名 |
| `achievement` | `participant`（出場）／`best4`／`best8`／`main_entry`（本大会出場）／`regional_entrant`（地区大会出場） |
| `source_id` | `data/master/sources.csv` の出典ID |
| `verified_at` | 確認日 |
| `notes` | 補足（校名の判断、21世紀枠など） |

## 収録範囲

| 使い道 | ルール | 件数 |
|---|---|---|
| 選抜出場校の春季予選免除（北海道・神奈川・愛知・三重・広島） | ACR000001/008/012/013/023 | 32（全出場校） |
| 茨城 前年秋ベスト4 | ACR000004 | 4 |
| 埼玉 前年秋ベスト8 | ACR000005 | 8 |
| 千葉 前年秋ベスト8 | ACR000006 | 8 |
| 岐阜 前年秋ベスト4 | ACR000010 | 4 |
| 兵庫 前年秋の近畿大会出場校 | ACR000015 | 3 |
| 岡山 前年秋ベスト8 | ACR000017 | 8 |
| 東京 前年秋の本大会出場校 | ACR000020 | 64（1次予選突破62＋夏の甲子園出場で予選免除2） |

出典は主に高校野球ドットコムの記事（二次資料）。選抜の出場校は選考当日のデイリースポーツ記事とも照合した。各県高野連の公式記録で確認できたら出典を差し替える。

検証：`python -m unittest discover -s tests -t tests -p test_initial_state_2026.py`
