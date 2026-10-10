# Stage 43G-31：新旧年度を横断する学校・選手の読取専用画面データ

作成日：2026-10-11

## 背景
Stage43G-30では、旧ISO年度`historical_matches.sqlite3`と架空の論理日付を使う`fictional_option_a_v2.sqlite3`の年度別ソース判定、封印・原本ハッシュ照合、重複年度拒否を設計した。次に、既存の正式GUIへ無条件に組み込まず、学校と選手の閲覧に限定した別APIを追加する。

## 実装対象
- `phase2_engine/career_cross_era_browse_model.py`
- `CareerCrossEraBrowseModel(slot_root).school_years([2026,10000], school_id)`
- `CareerCrossEraBrowseModel(slot_root).player_years([2026,10000], school_id, player_id)`
- `tests/test_stage43g31_cross_era_browse_model.py`
- `.github/workflows/career-cross-era-browse.yml`

## 閲覧ルール
1. 呼び出し時にはG-30の`CareerCrossEraReadGate.inspect`を必ず通し、年度の重複・未保存・未封印・旧ISO/v2境界不整合を拒否。既定の`verify_source=True`では全原本を深く再検証。
2. 学校ページは年度別の試合一覧、試合日付の表現、学校から見た勝敗を保存済み試合だけから取り出す。全国大会優勝校や完成した大会表の推定はしない。
3. 旧年度の試合は旧DB内の学校別索引で抽出し、各保存JSON SHA・試合ID・年度・得点を照合。v2年度は専用sidecarの封印済み年間read modelから、認可された論理日付と得点を照合。
4. 選手ページは選択した学校・年度の保存済み20人ロスター・恒久`player_id`を照合する。選択年度に所属していなければ`not_on_saved_school_year_roster`を明示する。**氏名・背番号・ポジションによる同一人物推定を行わない。**
5. 旧年度の個人成績は既存の`CareerPlayerRecordView`からA方式box scoreを検証し、その**1年度の記録のみ**表示。v2年度の個人成績はG-29の独立した封印済みキャッシュから取得する。
6. v2側キャッシュが無い場合は読み取り時に勝手に生成せず拒否する。選手がロスターに所属していても、その年に対象選手のbox scoreがなければ「記録なし」とする。0打席・0試合を実績があるように補完しない。
7. 年度をまたぐ勝敗・通算打率・歴代最多安打等は合算しない。中間年度が未登録なら`unverified_intervening_year_intervals`として明示し、`combined_career_totals=None`を返す。
8. 参照は読み取り専用で、旧DB、v2原本、ロスター、派生成績キャッシュ、カレンダーを更新しない。

## E2E例（合成）
- 2026の実在学校IDを使った**合成**試合と、10000年度の合成v2試合をそれぞれ封印。
- 学校ページは`YYYY-MM-DD`／`G10000:MM-DD`の日付が年度ごとに違うことと、学校別保存済み試合だけを返すことを確認。
- 2026年度に所属した選手と10000年度に所属した選手が、同じ学校の選手だからといって単一人物扱いされないことを確認。
- G-29専用キャッシュの有無やSHA改ざん、不正選手ID、未封印年度、欠落年度と旧DB不存在を検証。

## 留保
- **2026から10000年度まで実際に連続進行したゲームを検証したわけではない。** 10000年度は完全に合成fixture。全国大会の年度間進行・新年度の公式参加資格・入学卒業の現実的生成は対象外。
- 今回の画面データはheadless APIであり、Tkinterの正式画面へのルーティング接続はしていない。
- 新旧の通算選手記録とランキング、学校年度別の全国実績、長期間の巨大DBに対する性能最適化・保存先分割・復旧は後続工程。
- G-30の安全ゲートが通っても年度間の連続性は証明していない。学校名や所属履歴も利用者が承認した既存マスターに依存する。

## mainへの反映条件
G-30がmainへマージされた後、G-31のPython3.12全unittest、関東17校E2E、専用CI、関連する読み取り専用ゲートのCIが成功し、GitHub上でマージ可能なこと。
