# ココシミュNew：閲覧機能のデータ要求・正本対応（Stage 42）

更新日：2026-10-10  
対応台帳：`docs/design/viewing_feature_catalog_stage42.csv`  
位置づけ：**データの有無を調べるための依存関係表。追加のDBカラムや計算ロジックをここで確定しない。**

## 1. 原則：表示できる根拠を必ず追跡する

閲覧機能の基本的な流れ：

```text
学校・大会マスター / 学年別選手の正本
                ＋
試合シミュレーション結果（スコア／MatchEvent／GameStats）
                ↓
永続化（year, competition_id, match_id, school_id, player_id）
                ↓
BrowseRepository / PlayerStatsReadModel / 資格判定read model
                ↓
BrowseGuiModel
                ↓
簡易GUI／将来の正式GUI
```

ただし**史実二次資料**（例：2026広島西部）は別経路：

```text
研究用観測CSV＋根拠URL／公式未確認フラグ
   ↓
Stage32入力検証 → Stage33段階再生 → Stage34予選専用read model
   ↓
Stage35〜41の隔離試験プレビュー
```

上の2経路は学校ID照合や安全な画面遷移を共有できても、**同一の試合・同一のスコア・同一の大会結果レコードとしてマージしてはいけない**。

## 2. 画面と必要データの対応

| 機能群 | 主要な表示項目 | 既存の正本・API | データ依存・不足候補 | Stage42判定 |
|---|---|---|---|---|
| ホーム・日付（`VIEW-HOME/D​​ATE-*`） | 年度、試合日、シーズン概要、試合一覧、フィルタ | `BrowseGuiModel.home_summary()`、`date_choices()`、`matches_for_date_choice()`、SQLite `browse_seasons / matches_by_date` | ゲーム内現在日付、直近・未来日程の確定/未確定区別 | 基本GUI試作あり。ゲーム内日付は未確認 |
| 大会結果・組合せ（`VIEW-TOUR-001/002/003`） | 大会名、ラウンド、勝敗、優勝・準優勝 | SQLite `competition_results / matches_by_date`、`bracket_rounds()` | ブロック/敗者復活を単一MAIN風表に置換しない | GUI試作あり。複雑方式の表示は未完 |
| 進出関係（`VIEW-TOUR-004/005/006/010`） | 代表校、権利獲得試合、試合待機/対戦確定 | Stage34 `QualifierBrowseViews`、県→地区の設計・実行系 | 2026秋西25公式試合番号、32矢印、春秋8地区48経路未確認 | 広島隔離プレビューのみ／一部設計 |
| 試合スコア（`VIEW-MATCH-001/002`） | 2校、勝者、得点、日付、出典 | `DatedMatchRow`・`BrowseRepository.matches_on_date()` | 試合詳細画面での対象特定・欠損表示 | 基本GUI試作＋read model |
| 試合詳細・記録（`VIEW-MATCH-003〜008`） | イニング別得点、安打/失策、打席イベント、個人成績、起用 | `GameStats`、`events_for_match()`、`player_batter_game_stats()`、`player_pitcher_game_stats()` | イニング別得点/全選手交代/終了理由の記録保証がないため拡張・検証が必要 | 一部はAPIのみ。詳細UI候補 |
| 学校・戦績（`VIEW-SCHOOL-001〜005`） | 公式校名、県・地区、勝敗、得失点、試合履歴、ロスター | `master/schools.csv`、`school_records`、`school_matches`、`player_master` | 年度を跨ぐ正式所属地区・合同チーム扱いの設計 | 基本GUI試作＋マスター参照が一部未統合 |
| 学校能力（`VIEW-SCHOOL-006`） | 打撃、投手、守備、走塁、層の厚さ | `PlayerAbilitySnapshot`→`TeamStrengthSnapshot`、`config/abilities` | 能力の時点、先発/秋移行、適性を画面用に安定供給 | 設計先行。学校固定値は禁止 |
| 学校と予選の橋渡し（`VIEW-SCHOOL-007`） | 観測校名→正式ID→2026年ゲーム戦績 | Stage39 18校ID台帳、Stage40読取SQLite事前照合、Stage41往復 | 対象外県・未登録校に誤適用しない。年度以外へ自動移動しない | 2026広島秋西専用 |
| 選手・ロスター（`VIEW-PLAYER-001〜005`） | 選手名、学年、背番号、守備位置、個人成績、能力 | `player_master`、`player_stats_read_model.py`、`PlayerAbilitySnapshot` | 能力スナップショットとゲーム詳細画面の接続 | 基本GUI試作、一部read model/設計 |
| 選手年度横断（`VIEW-PLAYER-006/007`） | 学年進行、卒業、通算成績、年度別成績 | `docs/design/player_master_gui_contract.md`、年度別`player_master` | 年跨ぎidentityの再確認。IDが継続しなければ通算集計禁止 | 将来候補。実装状態をStage43で再調査 |
| 打撃・投手ランキング（`VIEW-RANK-001〜003`） | 打率、OPS、HR、ERA、WHIP、Kほか | `PlayerStatsReadModel`、`player_rankings_v1.json` | 対象大会、規定打席・投球回、率/積算指標の表示条件 | 大会GUI試作、年度全体APIはあり |
| 歴史・分析（`VIEW-HISTORY-*`、`VIEW-ANALYTICS-*`） | 歴代優勝、複数年度推移、学校比較、県別勝率 | 年度別`school_records / competition_results / GameStats` | 旧大会IDの正規化、年度横断クエリ、選手identity、出場校数≠大会参加チーム数 | 多くは将来候補 |
| データ出力（`VIEW-EXPORT-*`） | 条件付きCSV、記録レポート | `browse_views.save_season_browse_views()`等の既存出力 | GUIフィルタを反映した出力や来歴の同梱 | CSV書出基盤はあるがGUI任意出力は候補 |
| 出典・未確認（`VIEW-META-*`） | score_source、date_source、公式/二次/未確認、結果待機 | `DatedMatchRow`、`QualifierBrowseViews`、Stage25〜41 | 未確認データの偽の勝敗・日付・順位付けを防止 | 正規GUIでの統一凡例は未完 |

## 3. データ単位と推奨キー

| 事実の種類 | 主キー・識別 | 作成者・正本 | 禁止事項 |
|---|---|---|---|
| 学校マスター | `school_id` | 全国の正式`master/schools.csv`、所属マスター | 略称・似た名前からIDを作る |
| 学校の年度戦績 | `year + school_id` | `SchoolRecordRow`/SQLite `school_records` | 史実の二次結果をゲーム内戦績へ加算する |
| 大会結果 | `year + competition_id` | `CompetitionResultRow` | 年度の違う大会を単一結果として集計する |
| 試合結果 | `year + competition_id + match_id` | `DatedMatchRow`/SQLite `matches_by_date` | `match_id`単独で全年度一意と仮定する |
| 選手マスター | `year + player_id` | `player_master` | 年跨ぎidentity確認なしで通算集計する |
| 試合イベント | 試合キー＋`event_no` | `match_events` / MatchSimulator | 打席イベントだけから投手交代まで復元したことにする |
| 選手の試合成績 | 試合キー＋`player_id` | batter/pitcher GameStats | 率指標を正本値として保持する |
| 予選二次史実 | 研究資料の固有試合ID＋`source_kind`＋checkpoint | Stage32〜34 | 未実施試合の勝者・日時・正式矢印を見せる |
| TeamStrength | 年/時点＋起用条件＋snapshot | 選手能力・起用・configの派生値 | 学校マスターに固定打撃力・投手力を持たせる |

## 4. 計算値と正本の区別

- **打率、出塁率、長打率、OPS**：`at_bats`、`hits`、`walks`等の整数countsから再計算する。
- **防御率、WHIP、奪三振率**：投手の`outs_recorded`、自責点、走者数等から算出する。投球回は`6.2`のような浮動小数では記録しない。
- **学校勝率**：勝敗と試合数の集計基準を固定。不戦勝・不戦敗の扱いを勝率の脚注に示す。
- **学校能力**：その試合/時点の選手・起用から導出するsnapshot。過去試合と現在の学校能力を混同しない。
- **歴代記録**：年度や大会方式の差を吸収する必要がある。集計の元レコードと対象範囲を必ず表示する。

## 5. データ状態と空欄の意味

| 状態 | 表示案 | してはいけないこと |
|---|---|---|
| 試合日未定 | 「日付未定」 | カレンダーの会期全日へ試合を均等に割当てる |
| 対戦校未確定 | 「対戦校待ち」 | 後の結果CSVから未来の対戦校を先出しする |
| 勝敗未確定 | 「結果待ち」 | 中間データや予想から勝者を作る |
| イベント/得点の未収録 | 「記録なし」「－」 | 0点、0打席、0防御率と同一視する |
| 史実二次資料からの結果日付 | 「二次結果日付」 | 公式発表の試合日程であると表示する |
| 年度跨ぎ選手の継続性未確認 | 「通算集計不可」 | 同名選手を自動で統合する |
| 読取対象DBに学校がない | 「対象年度の戦績なし」 | 同名他校・別年度へフォールバックする |
| 公式ルール根拠未確認 | 「公式ルート未確認」 | 本番大会エンジンや任意順位戦を解禁する |

## 6. P0着手前のデータ依存チェック（Stage43向け）

- [ ] 試合詳細で見せたい全項目が `GameStats` と `MatchEvent` に実在するか、保存先と試合IDを列挙する
- [ ] イニング別得点・守備失策・交代/継投などは保存仕様が必要か判定する
- [ ] 学校能力を閲覧用snapshotへ取り出す時点と条件（年度・大会・試合）を決める
- [ ] 選手年度横断のID継続性を実装・監査できるか、既存の最新コードで確認する
- [ ] 県別・全国の正式大会、地区予選の状態を同一の「大会結果」へ安全に表せるか確認する
- [ ] 史実とゲーム生成を混ぜない識別子・来歴フラグをUIへ必ず渡す
- [ ] SQLite schema初期化の副作用を整理する：**read-only GUIの表示操作**と`BrowseRepository`接続時のDDL動作を区別する
- [ ] 実機での日本語表示・表の列数・スクロール・DPI・キーボード操作の受入条件を文書化する

Stage43は、このチェックを実データ・実コードと照合して「P0機能のデータ充足」「保存・集計機能の追加が必要」「GUIだけで足りる」を決める工程。**Stage42はデータを追加保存しない設計文書工程**である。

## 7. 恒久的に維持する境界

2026広島秋西の学校ID18校の一意照合は既にできている。ただし公式試合番号25件・敗者矢印32件、および春秋8季節地区の進出経路48件は未確認で、**本番FMT025・任意順位戦の実行権限とは別問題**。正式GUIの完成も、今回の文書作成によって宣言しない。

## 8. Stage 43準備追記：A方式の長期保存に必要な正本（2026-10-10）

過去試合の長期保存要件を **A方式（最終スコア・イニング別得点・試合別個人成績）** とする。正式仕様は [historical_match_retention_option_a.md](historical_match_retention_option_a.md) を参照。

| 正本 | データの現状 | 後続で必要な処理 |
|---|---|---|
| 試合基本結果 | matches_by_date / competition_results / ability_matches が存在 | 全確定公式戦での記録漏れ・大会方式・年度を監査 |
| 半イニング別得点 | 現行の専用永続スキーマは未実装 | MatchSimulator確定時に得点列を保存。未実施と0点を区別 |
| チームの得点・安打・失策 | team_game_statsが存在 | 全確定対象での適用範囲と欠損表示を監査 |
| 打者・投手の試合別成績 | batter_game_stats / pitcher_game_statsが存在 | player_idの年度内・年度横断同一性を検証、履歴読出しを整備 |
| 全打席イベント列 | match_eventsが存在 | A方式の必須保存から外す。既存データ互換性を維持して永続保存の任意化を別途設計 |

**既存のMatchEventを使って試合やGameStatsを計算する処理は維持できる。A方式の履歴参照でイベント保存に依存しないことが目標。** 旧年度のイニング得点は、最終スコアや最終回だけから復元しない。未収録の場合はその旨を表示する。

年度の新規保存は過去の既存年度を上書きしないこと。現在のreplace_season_views等に同一年度DELETE→再登録があるため、次年度移行と明示的再構築を区別する防護が必要。

この追記は**保存方式の要件整理**であり、SQLite変更・正式GUI作成・複数年進行・イニング別得点保存が実装済みになったことを意味しない。
