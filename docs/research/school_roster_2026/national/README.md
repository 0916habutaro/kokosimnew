# 全国・複数年度の学校別部員数調査（参考資料）

> **未確定の実測調査・分析用原表**。全国の人数分布にそのまま当てはめず、ゲーム設定・学校マスターへの自動反映は禁止。

## 収録範囲

以下は「2026_roster_research_model_fits_v2 (1).xlsx」（16シート、2026-11-07時点）のうち、データシートからCSVに抽出したものです。**行数はユニークな学校数ではありません**。

| CSV | 元シート | 記録内容 |
|---|---|---|
| [prefecture_members_2022_2026.csv](prefecture_members_2022_2026.csv) | 全国5年度 | 47都道府県×2022〜2026年・年次の都道府県別加盟校数と部員数（240データ行） |
| [national_strong_regular_schools.csv](national_strong_regular_schools.csv) | 強豪常連校資料 | 全国から収集した強豪・常連校等の資料229行。学校・年度の重複、未確認や除外も含む |
| [strong_school_year_comparison.csv](strong_school_year_comparison.csv) | 強豪校年度比較 | 強豪校の2024〜2026年夏の部員数比較57行 |
| [school_2026_review_99.csv](school_2026_review_99.csv) | 学校別99校 | 2026年の学校別調査99行（代表校、非代表校、保留を含む） |
| [nagano_school_members_by_year.csv](nagano_school_members_by_year.csv) | 長野学校年度資料 | 長野県の複数年度学校別資料74行。役割区分が不明な資料は未確定 |
| [additional_school_source_records.csv](additional_school_source_records.csv) | 追加学校提供資料 | 追加学校の確認資料16行 |
| [school_year_comparison_examples.csv](school_year_comparison_examples.csv) | 同一校年度比較 | 同じ学校の年度別比較例22行 |
| [school_research_audit_log.csv](school_research_audit_log.csv) | 今回調査ログ | 調査・照合・未採用の記録424行 |
| [original_exploratory_model_fits.csv](original_exploratory_model_fits.csv) | モデル比較 | 初期のPoisson／負の二項探索比較15行 |
| [chiba_school_members_2022_2026.csv](chiba_school_members_2022_2026.csv) | 千葉全校5年度 | 千葉県の学校別×年度データ860行。全国モデル検証の部分標本 |

初期段階の解釈は[2026_school_roster_model_research.md](2026_school_roster_model_research.md)も参照。千葉県の学校規模・常連度の結合・交差検証は[親ディレクトリ](../)の2026_chiba_*ファイルに収録。

## 出典・品質・用途

- **全国5年度**は[日本高野連硬式野球部員数](https://www.jhbf.or.jp/data/statistical/koushiki/2026.html)の年次県別公表値。学校別の実測人数とは異なる。集計年ごとの出典URLはCSV各行を参照。
- 強豪校・学校別資料は新聞記事、学校公式ページ、各高野連の発表等が混在。**人数の集計日、マネージャーの包含、選手数への換算可否、学校・年度の重複**をCSVの品質欄・注記・出典URLで確認する。
- 夏の代表校・常連校を多く集めた標本は全国3,746校の**無作為標本ではない**。全国分布の推定にそのまま用いない。
- 県別部員総数は県の加盟校平均の比較には有効だが、学校の部員数変動に対する県固定補正の因果根拠ではない。
- Poisson・負の二項の比較は探索的。学校間の分散と同一校の年次変動を区別してから最終採用する。
- 出典時点の学校名、学校改編、複数校合同、役割区分などは未確定値を推定しない。
- 原本16シートExcelにある「概要」「全国校正検証」「定義・検証」等のメモ・表はこのCSV一式と完全同一ではない。必要に応じ原本に照合する。
- 数値仕様が確定するまでゲームの `config/` と `data/master/` には反映しない。

## 後続の学校特性分析との関係

部員数を生成するときは県の平均値より**学校規模・学校固有募集力・過去の大会常連度・年度変動**を優先して検討する。各要素の係数は現時点では未確定。
