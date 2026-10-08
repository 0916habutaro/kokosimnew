# Stage 13E-3G-4：学校ID・地区所属・順位戦参照データのデータ契約

## 既存マスターを変更しない

2026年の登録実体は3,746校／3,746プログラム／6,871地区所属。大容量のGitHubファイル閲覧で空のレスポンスが返っても、それはソースファイル欠損の証拠にはならない。既存school_id・program_id・area_id・stage_group_idを使用し、追加の対応表だけを登録する。

## 検証パイプライン

`audit_ranking_school_mapping_2026(data_dir)`：
- 参照CSV34件と対応CSV34件の`reference_id`集合・一意性一致
- masterの`federation_name`が観測名と一致した場合のみ`official_federation_name`
- 観測名と正式校名に差がある場合は11件の`post_qualification_rank_school_aliases.csv`で明示された県・school_id・master正式校名が完全一致すること
- 2026年硬式program_idと登録地区scheme（静岡ASM000051、広島ASM000077）の存在と一意性
- 既存`competition_stage_groups.source_area_ids`の厳密一致
- 実在越境カードは`review_cross_area_fixture`でgroup_id空欄
- 代表決定戦は`excluded_qualification_decider`でランキングsidecarへ取り込めない
- 観測CSVと対応CSVのmapping_statusが一致

`build_verified_fmt025_2026_daily_sidecar(...)`：
- FMT025のみ。公式参照の同一大会・同一group_id・同一試合日の`mapped_same_area_ranking_reference`だけ抽出
- 追加試合参加校のschool_idが、指定された`locked_school_ids`の部分集合であることを必須とする
- 年次の公式スコア・勝敗は不使用。新しい`ScheduledRankingSidecar`は未実施状態
- 地区越境カード・代表決定戦は除外。未確認の年度対戦カードを推測しない
- 1日分の順位戦のみ生成可能であり、**同一groupでの複数日イベント登録はまだ実施しない**

## FMT025の追加設計課題

例として静岡春の西部地区は4月4日と4月11日に試合が存在する。現行の`ScheduledCompetitionRuntime.ranking_sidecars`は`group_id`単位で1イベントしか持てない。次段階で`post-ranking-instance-id`を発行し、同じgroup_idの独立した日付バッチでもmatch_idが衝突しない契約へ拡張する。秋季静岡の越境カードはさらに別契約として扱う。

## 回帰・更新ルール

従来の予選進出出力・MAIN出場者・成績read modelの通常試合には加算せず、オプトインで順位決定戦を生成する。学校IDや代表確定済み校の入力が間違っていればエラーとする。
