# Stage 13E-3G-32：FMT025を実行する前の入力契約・公式証拠release-lock

実装日：2026-10-09

## 狙いと基本方針

Stage31では「明示された試合の対戦・勝者・敗者の進出先」から、一次予選と敗者復活を含むDAGのread-only再生を実装した。Stage32では、そのDAGをアプリ内部に渡す直前の**バージョン付き入力契約と失敗時の拒否機構**を独立させる。

今回も**本番ゲームのFMT025スケジューラは変更しない**。通常の試合生成・大会進行やGUIから呼び出せる稼働経路は追加していない。将来の本体統合に向けた前処理APIであり、入力側が勝手に `official_draw_verified=true` と書いても承認しない。

## バージョン1の入力契約

`phase2_engine/hiroshima_fmt025_input_preflight.py` で `fmt025-explicit-input-v1` を定義した。入力フィールドは固定：

- `contract_version`、`format_model_id=FMT025`、`execution_intent=read_only_preflight`
- `source_kind`、`year`、`season`、`district_code`、`stage_group_id`
- `qualifier_slots`、`entrant_ids`、`direct_main_entry_ids`
- `matches[]`（試合ID、フェーズ、二つの出場元、明示的な勝者・敗者の次試合、勝者の進出枠有無、条件付き再挑戦許可）、`winners_by_match`
- `official_draw_verified`、`official_loser_selector_verified`、`release_approved`、`optional_ranking_requested` はこのStageでは全て`false`以外を拒否

余計なJSONフィールド、欠けたフィールド、JSON重複キー、不正なbool、誤った版・出場枠、参加校の重複を拒否。受入れ済みread-only入力はSHA-256で識別できる。ただし**SHA-256は入力の識別だけで公式ソースの真正性証明ではない**。

`preflight_fmt025_input(payload, data_dir=...)` はStage31の `replay_explicit_match_dag()` またはStage25の史実25/32接続を読み、戻り値で試合数・参加校数・試合間転送数・出場枠と根拠等級を返す。ファイル更新・本体大会進行は実行しない。

### 入力の来歴は2種類のみ

1. `fictional_inline`：実年度・地区・大会IDを名乗れない純粋な架空の明示試合グラフ。外部が指定した学校・勝者を機械的に再生する。
2. `stage25_2026_west_secondary`：2026年広島秋西だけの、Stage25の登録済み試合結果・学校別接続を参照して再生する。ユーザー側で対戦カード・得点・校名を差し替えて「2026公式記録」に昇格させることはできない。この入力の証拠等級は必ず**二次結果の史実**であり、公式の試合番号・敗者移動矢印を証明しない。

他地区や未来年の公式ルート、何も根拠のない `federation_official_pdf` 等のsource_kindは未許可。投入したJSONに本人が書いた根拠・許可フラグを**信頼できる外部審査者の承認とみなさない**。

### 本番接続前の明示的な拒否API

`require_live_fmt025_release(preflight)` は現Stageで常に**例外を送出**する。この経路を通さずに `read_only` 出力をゲーム本体へ入れる実装は許可されない。read-onlyの成功、または戻り値に`authorized_for_live_fmt025=True`を偽装する操作を行ってもlive許可は成立しない。真の本番接続実装には、独立した正式証拠・年度別ルール・人手レビューの認証機構が将来別途必要。

## 季節地区別のRelease Lock

`data/competitions/2026/hiroshima_fmt025_input_release_locks_stage13e3g32.csv` に春秋8地区の**全8件**を登録した。

| 項目 | 現在値 |
| --- | --- |
| 2026季節地区 | 春4＋秋4＝8件 |
| Stage30の公式資料確認未達 | 各地区6条件、合計48条件 |
| 一次カード・一次敗者→敗者復活の公式配線 | 未確認 |
| 二位校側対戦カード・C/D等横断決定の公式個別配線 | 未確認 |
| 独立した本番release承認 | `no` |
| 本番FMT025・任意順位戦 | `no` |
| 史実25試合のread-only再生 | 2026秋西のみ `yes`（公式組み合わせを認証した意味ではない） |

`phase2_engine/hiroshima_stage13e3g32.py` はStage30・31の監査と接続し、年度、季節、地区ID、48個別根拠、8枚のrelease-lock、2件の入力JSONを検査する。

## GitHubに追加したread-only入力例

- `data/research/2026/hiroshima_fmt025_preflight_example_fictional_four_schools_stage13e3g32.json`：架空4校の明示試合3件、敗者移動2件、通過3校。年度・地区を「公式実例」とする設定を持たない。
- `data/research/2026/hiroshima_fmt025_preflight_example_observed_2026_autumn_west_stage13e3g32.json`：2026秋西の史実25試合・18校・32接続・7校通過を既存DBからのみread-only取得。
- `tests/test_stage13e3g32_hiroshima_fmt025_preflight.py`：版誤り、JSON属性欠損・余分、重複キー、試合間の未指定・未来接続、誤勝者、年度・大会詐称、条件の無根拠な解除、release-lock改ざん等を拒否。
- `data/research/2026/research_pending_queue.csv`：RS2026026に今回の到達点を保存。

## 今後の接続条件

1. 2026春秋各季節・地区の**公式組み合わせと敗者転送の根拠**を、Stage30の未確認48件のどの要件に対応するか明記して取得する。
2. 個別の試合番号と転送矢印を、原本のページ位置・取得日時・ハッシュとともに独立審査する。2026秋西の25番号・32矢印は現在未確認のまま。
3. 原本に根拠を持つ公式ルールの年度適用、必要なseed抽選と人数差、遅延試合生成・大会間の進出枠保存を別stageで証明する。
4. その後、別途認証されたrelease機構を設計し、初めてゲーム本体と統合する。read-onlyの戻り値でlive認証を代用してはならない。

**Stage32の完了条件：バージョン付き入力契約、2種の入力例の検証、8×6のrelease-lockを備えたread-only実行前審査と回帰テスト。実際の2026公式敗者転送の証明・本番FMT025接続は対象外。**
