# Stage 12T GUI実行確認・フィルタ・トーナメント・画面遷移

作成日: 2026-10-07

## 目的

Stage 12Sで作成したread-only GUIを実際に起動して描画確認し、閲覧操作として不足していた以下を追加する。

- 日付画面の大会フィルタ
- 日付画面の都道府県フィルタ
- 大会画面のトーナメント表示
- 日付→大会
- 日付→学校
- 大会→学校
- 学校→大会
- 学校→対戦相手

書き込み機能は引き続き追加しない。

## GUI実行確認

利用可能なLinux実行環境でTkinter 8.6とXvfbを使用し、GUIプロセスを実際に起動した。

確認用SQLiteには次のサンプルを投入した。

- 年度: 2026
- 試合: 5
- 大会: 2
- 学校: 4

初回描画:

- ウィンドウ: 1240×820
- タブ:
  - 日付別試合
  - 大会結果
  - 学校戦績
- 初期日付: 2026-07-10
- 初期表示: 2試合

拡張後の操作確認:

- 都道府県13フィルタ: 2試合表示
- 大会画面へ遷移: 成功
- トーナメントCanvas: 準決勝2試合→決勝1試合を描画
- 学校S1へ遷移: 成功
- 学校試合履歴: 3件表示

これはユーザーのWindows PCそのものではなく、仮想ディスプレイ上の実行確認である。Windows実機確認は別途必要。

## 実装構成

Stage 12Sの `BrowseApp` は残す。

Stage 12Tでは:

`phase2_engine/browse_gui_enhanced.py`

へ `EnhancedBrowseApp` を追加する。

`browse_gui.py` のmainだけがEnhancedBrowseAppを起動する。

これによりStage 12Sの画面契約を残しながら、機能追加を分離できる。

## 日付別試合フィルタ

従来:

- 試合日

追加:

- 大会
- 都道府県

### 大会

`すべての大会` または個別大会を選択する。

### 都道府県

`すべての都道府県` または都道府県コードを選択する。

試合のteam1またはteam2のどちらかが選択都道府県に所属すれば表示対象とする。

SQLiteでは `matches_by_date` と `school_records` をteam1/team2の双方でLEFT JOINする。

追加repository API:

- `list_prefecture_codes(year)`
- `matches_for_date_filtered(year, date, competition_id=..., prefecture_code=...)`

## トーナメント表示

大会画面内にサブタブを追加する。

- 試合一覧
- トーナメント表

Stage 12Q/12Rのmatchデータから:

- stage_code
- round_no
- round_name
- team1/team2
- score
- winner

を利用する。

原則として `stage_code=MAIN` の `round_no > 0` をトーナメント対象にする。

MAINが存在しない場合は、round_noを持つ試合へフォールバックする。

### 接続線

ラウンドAの試合数が次ラウンドBのちょうど2倍の場合だけ、2試合→1試合の接続線を描画する。

不規則な大会方式で実際のfeeder関係がread modelにない場合は、誤った接続線を推測しない。

試合カード自体はラウンド列として表示する。

## 画面遷移

### 日付別試合

ダブルクリック:

- 大会名 → 大会画面
- チーム1 → 学校画面
- チーム2 → 学校画面
- 勝者 → 学校画面

### 大会結果

試合一覧のダブルクリック:

- チーム1 → 学校画面
- チーム2 → 学校画面
- 勝者 → 学校画面

### 学校戦績

試合履歴のダブルクリック:

- 大会名 → 大会画面
- 対戦相手 → 相手校の学校画面

遷移時は年度を維持する。

## GUIモデル

`browse_gui_model.py` へ追加:

- `ALL_COMPETITIONS_LABEL`
- `ALL_PREFECTURES_LABEL`
- `BracketRound`
- `prefecture_choices()`
- フィルタ付き `matches_for_date_choice()`
- `bracket_rounds()`

Tkinter非依存でテストできる。

## read-only維持

Enhanced GUIにも以下は置かない。

- INSERT
- UPDATE
- DELETE
- replace_season_views
- save_season_browse_repository

Stage 12Rの検索APIだけを利用する。

## 検証

### 実行確認

- Tkinter 8.6
- Xvfb
- 1240×820描画
- 3タブ
- SQLiteロード
- 日付フィルタ
- トーナメント描画
- 大会画面遷移
- 学校画面遷移

### ローカル対象テスト

GUIハーネスで6件を実行しPASS。

### リポジトリ回帰テスト

Stage 12T専用テストを追加する。

- 都道府県候補
- 日付×都道府県フィルタ
- 日付×大会フィルタ
- 日付未定
- bracket round構造
- フィルタ表示ラベル
- navigation source contract
- EnhancedBrowseApp起動
- read-only contract

全Pythonテストスイートは本作業環境では未実行。

## 次工程

Windows実機での表示確認後、GUI改善候補は以下。

1. トーナメントカードから学校画面への直接遷移
2. 都道府県コードを都道府県名表示へ変換
3. 大会種別・春夏秋フィルタ
4. ホーム画面 / 指定日の主要試合
5. 行の色分け・勝者強調・列幅保存
6. シミュレーション進行GUI

実績日更新はStage 12Oのdueキューで後追い可能なため、GUI開発とは分離して継続できる。
