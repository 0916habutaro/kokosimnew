# Stage 13E-3G-4：既存学校マスター復旧確認・2026順位戦の学校ID／地区照合

実施日：2026-10-08

## 重要な訂正

前工程3G-3ではGitHubコネクタの大容量ファイル取得が空文字を返したため、`schools.csv`と`school_area_memberships.csv`を誤って「空」と判断していた。

**GitHubのGit blob APIで実ファイルを読み取り直すと、学校マスター3,746件／硬式野球部3,746件／地区所属6,871件が既にmainに登録されていた。**

データそのものは欠損していない。よってPhase 1マスターの再収集や上書きは不要と判断し、既存の恒久学校ID・プログラムID・2026年の地区所属を参照する小さな対応表を追加する。

## 確認データと結果

- `data/master/schools.csv`：3,746校。school_id / federation_name / official_name / prefecture_code
- `data/master/baseball_programs.csv`：3,746件。program_id↔school_id、2026年hardball
- `data/areas/school_area_memberships.csv`：6,871件。program_id / area_id / scheme_id / reference_year
- `data/competitions/competition_stage_groups.csv`：地区ごとの`source_area_ids`と所属グループ
- `data/competitions/2026/post_qualification_rank_observations.csv`：34実試合参考資料、53種類の学校名

公式高野連掲載名（`federation_name`）と照合できた42校はそのまま学校IDへ対応付けた。残る11件は略称・正式校名差などを1校ずつ検証し、独立したalias CSVに校名・県コード・school_id・master公式名称を保存した。**曖昧な学校名を部分一致だけで自動確定しない。**

`post_qualification_rank_school_mapping.csv`の34レコードの区分：

| 分類 | 件数 | 対応 |
| --- | ---: | --- |
| FMT022（徳島・沖縄） | 5 | 学校IDを確定。4シード確定後の実行を別途必須とする |
| FMT025 静岡同地区 | 25 | 両校の学校ID・公式2026地区所属・stage_group_idを確定 |
| FMT025 静岡越境 | 1 | **RR20260023** 藤枝明誠（中部AREA000068）対沼津東（東部AREA000067）。試合自体は存在するが単一地区sidecarへ誤配置しない |
| 広島代表決定戦 | 3 | 学校ID・登録地区まで照合したが`qualification_decider_not_ranking`を維持。追加順位イベントへ登録禁止 |
| 合計 | **34** | 53校をIDに対応付け、実戦績のゲーム内転用はしない |

### 重要例外：静岡秋の実在越境カード

2026年8月30日の**藤枝明誠8対5沼津東**は複数の公開試合結果で確認できる。学校の2026年恒常地区所属を照合すると、藤枝明誠は中部、沼津東は東部に属する。

- [高校野球ドットコム・秋季静岡県大会予選上位決定戦](https://www.hb-nippon.com/tournaments/1923)
- [令和高校野球・8月30日清水庵原球場の順位決定戦](https://www.reiwa-hb-sch-and-res-gatr-fod.com/shizuoka/2026autumn/first-round/)

したがって、単純に「全カードを学校所属から地区別ステージに分配する」実装は誤り。学校の所属を事実と違う地区へ移すのではなく、このカードだけ`review_cross_area_fixture`・group_id空欄として別途大会方式を検討する。

## 登録・実装ファイル

- `data/competitions/2026/post_qualification_rank_school_aliases.csv`：11校の明示略称対応
- `data/competitions/2026/post_qualification_rank_school_mapping.csv`：34試合の両校school_id、地区ID、stage_group、保留区分
- `data/competitions/2026/post_qualification_rank_observations.csv`：`mapping_status`を新しい照合結果へ更新
- `phase2_engine/ranking_school_reconciliation_2026.py`：school/program/area/group/aliasの参照整合監査とFMT025の厳密日別sidecar生成
- `tests/test_stage13e3g4_school_id_reconciliation.py`：照合・異地区検出・誤分類拒否・負例の回帰テスト

## ランタイム接続に関する保証と制約

`build_verified_fmt025_2026_daily_sidecar()`は公式年次参照日＋同一地区groupの対戦だけを選別し、**既に確定した代表校のlocked_school_idsに両校が含まれている場合のみ**、勝敗未入力のsidecarを生成できる。実在のスコア・勝者を架空シミュレーションへコピーしない。

静岡では同じ地区で順位戦が**複数の日付**に行われた例がある。現行`ScheduledCompetitionRuntime`のsidecar登録キーはstage_group_idのみであり、同一地区の複数日バッチを一度に登録するとIDが衝突するため、今工程では**一日単位の生成まで**を安全な契約とし、複数日登録は次工程へ持ち越す。ユーザー操作・CLIが意図せず年間進行を変更しないよう、自動登録はしない。

静岡越境カードの表現と広島の真の代表確定後順位戦は未解決。FMT022/FMT025の研究タスクRS2026025/26はdesign_pendingのまま継続する。2026年の明治神宮大会は別件。

## 次工程

1. 複数日の同一グループ順位戦を`group_id + 年度日付 + event-id`で区別できる永続runtime設計へ拡張。
2. 静岡2026秋の中部・東部混合上位決定戦を、恒常地区予選と別の横断イベントで表現するか公式の大会規則から決定。
3. 広島の代表確定後に残る順位戦カードだけを再調査し、未確定区分を埋める。
4. 上記を終えてからRS2026025/26のdesign_pending解除可否を監査する。
