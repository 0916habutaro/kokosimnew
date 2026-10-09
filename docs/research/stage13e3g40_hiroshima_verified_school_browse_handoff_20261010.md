# Stage 13E-3G-40：確認済み学校IDから既存SQLite学校戦績への安全な画面遷移

調査・実装：2026-10-10

## 背景と分離方針

Stage39で**2026秋季広島西部の史実観測18校について、18/18校すべて正式学校マスターIDへ一意照合済み**になった。Stage35～39の予選プレビューは二次史実25試合のread-only段階再生であり、既存SQLiteの`school_records`や`matches_by_date`に保存される「ゲームがシミュレーションした年度別戦績」とは意味が異なる。

既存の学校詳細閲覧は`BrowseGuiModel.school_detail(year,school_id)`と`Stage13D3BrowseApp`の学校戦績タブ。Stage40では、プレビューで選んだ学校の正式IDをこの既存画面へ橋渡しするが、**2026史実の25試合を既存SQLiteのゲーム内得点／通算戦績に加算しない**。

## 新規のread-onlyブリッジ

`phase2_engine/hiroshima_stage13e3g40_school_browse_handoff.py`

`preflight_2026_west_school_browse_handoff(db_path, link, selected_browse_year=...)` の遷移条件：

1. Stage39で実マスター照合済みかつ**現在プレビューで見えている**学校の `SchoolMasterPreviewLink` をGUI側で取得し、親画面ではStage39マスターと同じ内容であることを再審査。
2. 正式`school_id`、`program_id`、県コード34、検証済み状態を確認。公式抽選確認済みの偽フラグなども拒否。
3. 親画面の現在の選択年度が **2026** であること。2025/2027等は拒否し、自動的に年度を変更しない。
4. 既存SQLiteの対象ファイルが**実際に存在すること**。`sqlite3.connect(file URI + ?mode=ro)`で、SQLiteファイル・新しいテーブルを勝手に作らず、**読み取り専用**で`school_records(year=2026, school_id=検証済みID)`を照合。
5. 該当行が唯一1件で、その`prefecture_code`が広島県`34`である場合だけ移動許可。該当行なし、異県、重複は拒否する。
6. 通常GUIの学校検索へ正式IDを渡し、そのIDの行が実際に見つかってから、既存学校戦績画面を表示する。学校名の文字列`LIKE`だけで別校へフォールバックしない。
7. 検証・遷移ではSQLiteへの書き込み・履歴追加は行わない。既存の学校戦績機能自身は以前からあるGUI実装の範囲で動作する。

`SchoolBrowseHandoff` は`allowed,reason,year,school_id,observed_name,official_name`と安全フラグを持つimmutable contract。**実SQLiteに2026校の戦績が存在しない場合は安全に拒否**し、学校マスターだけの情報ダイアログは従来どおり使える。

## GUI接続・操作

- 通常のStage13D3簡易GUIの大会タブ →「予選進行プレビュー（試験・別画面）」を開く。
- プレビューの史実2026広島西部を選び、「学校別戦績」タブで対象校を選択する。
- 「既存SQLiteの学校戦績へ移動（2026年のみ）」ボタンを押す。通常GUIの年度が2026で、該当`school_id`がSQLite内にも登録済みなら、通常GUIの学校戦績タブへ移動する。
- プレビューをSQLiteなしで独立起動したときは、この遷移ボタンを**disabled**として表示する。既存の学校マスター情報ダイアログは別ボタンから表示可能。
- 遷移が拒否された場合はその理由をプレビュー側で表示する。プレビューの年度や未公開結果、既存SQLiteの試合結果は変更しない。

### 表示する際の重要な凡例

**「既存SQLiteの学校戦績はゲーム内で生成された別データです。2026広島西部の二次史実25試合は合算されません。」**

SQLite内に同じ学校IDがあることは、2026秋季広島西部の史実25試合を実行済みと意味しない。別のseedでシミュレーションされたデータを同じ史実として描くこともしない。

## 実装・テストファイル

- `phase2_engine/hiroshima_stage13e3g40_school_browse_handoff.py`：2026年度・学校ID・県34の読み取り専用SQLite事前確認
- `phase2_engine/hiroshima_stage13e3g35_preview_gui.py`：単独起動は遷移不可、既存GUIからの場合のみ「SQLite学校戦績へ移動」を表示
- `phase2_engine/browse_gui_stage13d3.py`：Stage39再照合→SQLite preflight→既存学校戦績タブへID指定で移動
- `phase2_engine/hiroshima_stage13e3g40.py`：18/18校の合成SQLiteプローブと異年度・ファイル不在の監査
- `tests/test_stage13e3g40_hiroshima_verified_school_browse_handoff.py`：モックTkを使ったGUIイベント、欠損DB非生成、異年度、県外、重複ID、詐称link、学校検索対象不在、SQLite書込の不発生を検証
- `data/research/2026/research_pending_queue.csv`：工事進捗と残件を更新

## 制約と実機確認待ち

Stage36のWindows実機GUI確認6項目は**依然未実施**。今回の新しい画面移動もCIではheadless（Tk callback模擬）で検証し、ウィンドウの実描画、DPI/キーボード、操作性、既存DBのGUI経由での実機表示はWindows実機での手動検証が必要。

2026広島秋西の正式試合番号25件・敗者進行矢印32件は未確認。春秋8地区の経路ルール48件も引き続き未確認。本番FMT025・任意順位戦には接続しない。

**Stage40は、正式学校マスターIDでゲーム閲覧モデルへ安全に移動するための試験GUI機能であり、公式ルートの真正性を示すものではない。**
