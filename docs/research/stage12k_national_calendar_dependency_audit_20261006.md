# Stage 12K 全国大会カレンダー・依存関係監査

作成日: 2026-10-06

## 対象

- CMP000001 第98回選抜高等学校野球大会
- CMP000002 第108回全国高等学校野球選手権大会
- CMP000003 明治神宮外苑創建百年記念 第57回明治神宮野球大会 高校の部

## 既存状態

3大会とも competition master と season_calendar には登録済みだった。

また共通シーズンエンジンには既に以下の実行経路が存在する。

- 選抜: selection_rules を基に32校を構造選出
- 夏甲子園: 49地方大会の優勝校を qualification_rules で接続
- 神宮: 秋季地区大会9優勝校＋東京都秋季大会優勝校を qualification_rules で接続

一方で全国3大会の season_calendar は start/end だけで game_date_list が空だった。

## 選抜 CMP000001

公式大会日程・試合結果から、実試合日を以下の11日として登録した。

- 3/19
- 3/20
- 3/21
- 3/22
- 3/23
- 3/24
- 3/25
- 3/26
- 3/27
- 3/29
- 3/31

3/28と3/30は休養日。

3/25は第3試合が雨天順延となったが、第1・第2試合が完了しているため試合日として採用する。

組み合わせ抽選日は3/6。

### 出場依存

selection_rules:
- 12ルール
- quota合計32
- 一般選考30校＋21世紀枠2校

2026ゲームシーズンでは実在出場校32校を固定せず、前年秋季大会結果・地区別枠を基に構造的に選出する。

## 夏甲子園 CMP000002

実試合日は15日。

- 8/5
- 8/6
- 8/7
- 8/8
- 8/9
- 8/10
- 8/11
- 8/12
- 8/13
- 8/14
- 8/15
- 8/16
- 8/18
- 8/20
- 8/22

8/17・8/19・8/21は休養日。

組み合わせ抽選日は8/1。

### 出場依存

qualification_rules:
- 49ルール
- quota合計49
- CMP000023〜CMP000071の地方大会優勝校を1校ずつ接続

## 明治神宮 CMP000003

開催期間:
- 11/19〜11/24

高校の部:
- 北海道
- 東北
- 関東
- 東京
- 北信越
- 東海
- 近畿
- 中国
- 四国
- 九州

の10地区代表。

組み合わせ抽選日は10/17。

2026-10-06時点では抽選前なので、高校の部の個別 game_date_list は未確定のまま保持する。

### 出場依存

qualification_rules:
- 10ルール
- quota合計10
- CMP000013〜CMP000022の各優勝校を1校ずつ接続

実大会の代表校は秋季地区大会終了後に確定するが、ゲームの構造シミュレーションでは地区大会結果から10校を解決可能。

## Stage 12D旧監査について

audits/phase2/stage12d/stage12d_qualification_dependency_audit.csv には、Stage 12E以前のため一部神宮ルートが BLOCKED と記録されている。

これは履歴監査として残す。

現在の正しい状態はStage 12Kの dependency audit と現行テストで管理し、現行エンジンでは59件の qualification rule がすべて解決可能。

## 追加・更新

- season_calendar.csv
  - 選抜 game_date_list / draw_date
  - 夏甲子園 game_date_list / draw_date
  - 神宮 draw_date / pending注記
- phase2_sources.csv
- stage12k_national_calendar_audit_20261006.csv
- stage12k_national_dependency_audit_20261006.csv
- test_stage12k_national_calendar_dependency_audit.py

## 次工程

1. 全回帰テスト
2. 神宮は10/17抽選後に高校の部game_date_listを確定
3. Stage 12I/12Jで秋季県・地区大会を実績化し、神宮の実代表接続まで監査
