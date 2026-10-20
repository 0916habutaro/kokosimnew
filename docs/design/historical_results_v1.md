# 実在校過去戦績データ基盤 v1（初回PR）

## 目的と実装境界

2024〜2026年の春・夏・秋の公式大会について、史実の試合結果を独立したCSVとして収集・照合できる基盤を置く。**本PRでは実際の戦績データをまだ投入しない。** 追加したCSVはヘッダーのみ。テスト内の学校名と試合結果は全て架空であり史実ではない。

- 既存の data/master/schools.csv の school_id が学校同一性の正本。
- 既存の data/competitions/competitions.csv に該当する2026大会は competition_id で任意接続。2024・2025大会は対応IDが存在しなければ空欄のまま保留する。
- 「資料上の出場チーム」と「学校」を分けることで、合同チーム・名称変更・未照合校を安易に単独校へ転換しない。
- 史実はゲーム内の架空試合・SQLite・セーブ履歴・大会エンジンへ一切投入しない。
- 学校ごとの強さ・入部選手の質への接続は、本データの校正・完全性監査を行う後工程まで禁止。学校固定戦力をTeamStrengthへ直接加算しない。

## ファイル形式（UTF-8 / CSV / ヘッダー厳密一致）

リポジトリ直下の historical_data/ に以下の5ファイルを置く。

`data/` 以下には置かない。既存の互換性テスト（stage43g99〜の compatibility）は `data/` 以下のファイル一覧が旧版と一致することを確認しており、ファイルを追加すると失敗するため。

| ファイル | ID・主要フィールド | 役割 |
| --- | --- | --- |
| sources.csv | source_id, publisher, document_title, url, retrieved_at, verification_status | 大会ごとの原資料。公式 / 二次 / 未確認を区別 |
| tournaments.csv | tournament_id, season_year, season, competition_name, level, prefecture_code, competition_id, completion_status, source_id | 2024〜2026年の大会識別。既存competition_idは任意 |
| teams.csv | team_id, tournament_id, display_name, team_type | 大会内の出場チーム。single / joint |
| team_members.csv | team_id, school_id, observed_name, mapping_status, source_id | チーム構成校・資料上の学校名。verified / unresolved |
| matches.csv | match_id, tournament_id, game_date, round_label, home_team_id, away_team_id, home_score, away_score, result_status, source_id | 試合単位の史実。final / unplayed / abandoned |

- IDは文字列で一意に保持する。年度をまたいだ同名校・同名大会を表示名で紐付けない。
- sources.url は https URL、retrieved_at と game_date は YYYY-MM-DD。
- prefecture_code は data/master/prefectures.csv と同じ2桁ゼロ埋め（01〜47）。`2` のような1桁表記は拒否する。
- verified とする校名対応には既存school_idが必要。unresolved の場合school_idは空欄とし、自動類推で埋めない。
- joint のチームには2校以上、singleには1校の team_members を記録する。
- final の試合は正規の試合日と非負整数の両得点が必須。同点スコアは大会規則により引き分け・再試合の可能性があるため直ちには拒否しない。
- unplayed / abandoned は得点欄を空にする。没収・不戦・継続試合・サスペンデッド等の複雑なケースはv1で確定勝敗に換算せず、資料と照合して後続仕様を定める。
- 完了した大会と「その大会の全試合を収集済み」は**別概念**。completion_status=completed は大会の開催状況のみで、データ完全性を意味しない。
- 実在成績から能力を推定する際は、入学年度・3年生引退・地区差・対戦相手・欠損状況を評価する。欠損校を「弱小」とは扱わない。

## 検証と収集

実行コマンド:

    python -m historical_results.validate
    python -m unittest discover -s tests -p 'test_historical_results_v1.py' -v

検証処理はread-onlyで、5つのCSVと学校・大会マスターだけを参照する。ファイル欠落、ヘッダー相違、重複ID、外部参照違反、合同校数、資料のURL、日付・得点・結果種別の矛盾を検出し、異常時は終了コード1にする。

実在データを収集する第2工程では、まず山梨県2026年夏季大会の公表済み全出場チーム・全試合を収集し、出典URLと収集日を併記する。一次資料を優先し、二次資料との相違は unresolved / unverified のまま記録する。大量取得・保存・再配布に先立って提供元の利用条件・権利関係を確認する。

### 初回PRの受入基準

1. 5 CSVはヘッダーのみで史実の誤登録がない。
2. 架空fixtureによる正常・拒否テストが成功する。
3. 既存コード、ゲームセーブ、学校マスター、能力設定、試合結果を一切変更しない。
4. 日本語で境界・欠損・今後の校正方針を記録する。
