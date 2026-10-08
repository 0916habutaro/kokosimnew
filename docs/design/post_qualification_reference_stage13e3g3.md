# Stage 13E-3G-3：実大会参考データの取り込み契約

2026年の公式/公開試合結果は、**架空ゲームの試合結果や資格確定結果とは別テーブル**で管理する。

## ファイル

`data/competitions/2026/post_qualification_rank_observations.csv`：
`reference_id,competition_id,stage_id,format_model_id,stage_group_id,match_date,ranking_round_no,team1_name,team2_name,team1_score,team2_score,winner_name,reference_classification,mapping_status,source_url`

- `verified_ranking_only`：資格決定後に実施された順位戦。2026年の過去試合結果の**証拠**。
- `qualification_decider_not_ranking`：同じ地区内でも勝者によって出場権が決まる試合。任意順位戦の生成から厳格に除外。
- `mapping_status=names_not_mapped`：グループは判明しても正式学校IDが未照合。
- `mapping_status=group_and_names_not_mapped`：地区グループと学校IDの両方が未照合。
- 学校名表記は資料に沿って保持し、同名校や略称から自動school_idを推測しない。

## 実行への接続

`build_verified_fmt022_2026_sidecar(data_dir,competition_id,school_id_by_official_name,locked_school_ids,qualification_locked_on)`

- 全正式学校名→学校ID対応を明示入力する。
- 4校すべてがステージの**既に確定した**`locked_school_ids`と一致することを検証。
- 対応する実試合日と初戦2カードから、`ScheduledRankingSidecar`を生成する。
- **勝者・スコアは入力しない。** 架空年度の勝者は`resolve_date()`により別途決定する。
- 決勝（沖縄型）の参加校は準決勝実施後に動的に決定。史実決勝カード・結果を強制しない。
- 資格4校が不一致なら処理を拒否する。
- FMT025はグループ・school_id不足のため自動接続を拒否し、資格決定戦との誤分類を防ぐ。

監査：`validate_ranking_observations()`が参照ID重複、対象大会／ステージ不一致、日付・スコア形式、勝者不整合、同一対戦の重複、資格決定戦の混入、FMT022のstage_group IDを検査。公開情報と紐付いていないものは「正式取り込み完了」としない。

## 制限

現在のデータの校名→正式学校ID紐付けは未完。学校マスター、地区別所属の整備を優先する。本工程は**参照試合の登録・分類・実行のゲート設計**であり、個々の試合結果をゲーム成績に自動反映するものではない。
