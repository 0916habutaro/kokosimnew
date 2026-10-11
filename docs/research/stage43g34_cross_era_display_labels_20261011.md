# Stage 43G-34：履歴閲覧試験GUIの学校名・選手名と操作性を改善

作成日：2026-10-11

## 前提
Stage43G-32 PR #173は`14253d211dad9d4854c4c03b69224f721216cff0`でmain反映済み。Stage43G-33 PR #174の実Tk検証9件・旧GUI回帰12件が成功しており、Python全unittestと関東17校E2Eの完了・mainマージを別途確認する。

このStageのブランチはG-33の実装コミットを起点とする。#174のmain反映後、本PRの差分を再確認してからマージする。**G-33の未完了CIを成功済みと扱わない。**

## 実装
- `phase2_engine/career_cross_era_display_labels.py`を追加。保存済み学校IDで`data/master/schools.csv`を照合し、`display_name`、次に`federation_name`の順で表示する。学校IDは常に併記し、未知校を他校名と取り違えない。
- 同一IDがCSVに重複していれば拒否。学校名が未登録の場合は`学校ID（学校名未登録）`で表示する。表示ラベルは参照先の認証根拠とはならず、遷移は保存済みIDを使う。
- 選手名は`career_school_rosters`の**指定年度×指定学校**スナップショットから取得し、SHA、恒久`career_player_identities`と整合確認。個人名・同名・背番号だけで別年度の選手をつなげない。
- 別年度に所属データがない場合は`選手ID（この年度に氏名の確認なし）`とする。卒業・転校・姓名変更などは推測しない。
- `career_cross_era_gui_pilot.py`へ学校表示名・選手表示名・ID併記、対戦校表示、試合の`n～m / 合計件`表示を追加。TreeviewでEnterキーを押すと選択行を開く。Alt+左は戻るの補助操作。
- 既存`career_history_gui_pilot.py`から開くToplevelに学校マスターのルートを渡す。既存の学校・大会・試合・選手・通算成績表示は変更しない。
- 単独起動時は`--data-root data`を新たに使用する（既定は`data`）。

## 動作例

```bash
python -m phase2_engine.career_cross_era_gui_pilot \
  --data-root data --slot SAVE_SLOT --school-id SCH000001 --years 2026,10000
```

- 例中の`SCH000001`はID形式例。実際には該当セーブに試合が保存され、正式学校IDが存在する必要がある。
- 旧年度の年月日はISO、新しい10000年度以降の架空fixtureは`G{year}:MM-DD`と区別。正式2026日付を10000年度へ流用しない。
- 旧とv2の個人成績は合算しない。表示名が判明しても2026～10000年度の連続進行と同一選手の長期キャリアを証明しない。

## 安全性と性能
- 学校マスターCSVはGUI起動時に一回読込。年度別選手の名前は表示する学校・選択年度の保存済みロスターに限定し、名前を取得するために全全国校のロスターを一斉読み込みしない。
- 読取はSQLite`mode=ro`であり、ロスター・原本試合・v2成績キャッシュ・旧集計を更新しない。表示のために成績キャッシュを作成することもない。
- 欠落・重複学校ID、恒久選手ID改ざんは例外として画面提供を拒否し、同名校への推測代入はしない。

## 自動テスト
`tests/test_stage43g34_cross_era_display_labels.py`:
- 学校IDからの学校名／学校ID併記。
- 選択年度の所属選手表示、10000年度の別ロスターへ名前・IDを流用しない。
- 未登録学校・未知選手の明示表示。学校マスター重複や欠落を拒否。
- 選手identity SHA改変の拒否と、参照元SQLite不変。
- Xvfb実Tkで日本語と恒久IDを表示し、Enter→選手ページ→年度切替→戻るを検証。
- 既存GUIから開いた新窓にも正式学校名が渡り、旧GUI側の画面を変えないことを検証。

専用workflow `.github/workflows/career-cross-era-display-labels.yml` は新テストとG-33実Tk回帰を実行する。

## mainマージ条件と残課題
先行PR #174をmainマージした後、G-34専用Tk CI、Python3.12全unittest、関東8都県17校E2Eがすべて成功した場合のみG-34をmain反映。

正式GUIへの接続、全国3,000校×50/100年の負荷検証、本当の全国大会年度繰越、学校・選手の正式プロフィール、Windowsの日本語フォント・DPI・ショートカットの実機確認は後続。
