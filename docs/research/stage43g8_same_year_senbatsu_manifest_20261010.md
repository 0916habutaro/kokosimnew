# Stage 43G-8：同年センバツ全32校のゲーム内参加名簿と神奈川推薦資格監査

作成日：2026-10-10。前工程：Stage43G-7 PR #148（main反映済み）。
2027以降の実施内容はすべて**ゲーム用sandboxの明示参加校・2026方式を投影した仮日程**。史実2027代表校・公式選考ではない。

## 1. 2026方式の公式根拠

- 日本高野連「第98回選抜高校野球大会 大会要項」：センバツは予選方式ではなく推薦候補を選考委員会が審査・選出する。https://www.jhbf.or.jp/senbatsu/2026/guidance/
- 日本高野連「2026出場校」：選抜大会に実際に選ばれた全32校を一覧として公開。2026神奈川出場は横浜。https://www.jhbf.or.jp/senbatsu/2026/team/
- 神奈川県高野連「令和8年度春季神奈川県高等学校野球春季大会出場校一覧」（2026-03-28）：推薦枠・横浜1校、地区予選から川崎・横浜北23、横浜南・横須賀23、湘南・西湘18、北相17校。https://kanagawa-hbf.sakura.ne.jp/wp/wp-content/uploads/2026/03/%E4%BB%A4%E5%92%8C8%E5%B9%B4%E5%BA%A6%E7%A5%9E%E5%A5%88%E5%B7%9D%E7%9C%8C%E9%AB%98%E7%AD%89%E5%AD%A6%E6%A0%A1%E9%87%8E%E7%90%83%E6%98%A5%E5%AD%A3%E5%A4%A7%E4%BC%9A%E5%87%BA%E5%A0%B4%E6%A0%A1%E4%B8%80%E8%A6%A7.pdf
- 神奈川県高野連「2026春地区予選」：県内4地区の試合結果。https://kanagawa-hbf.sakura.ne.jp/preliminary/%E4%BB%A4%E5%92%8C%EF%BC%98%E5%B9%B4%E5%BA%A62026%E5%B9%B4%E6%98%A5%E5%AD%A3%E5%A4%A7%E4%BC%9A%E5%9C%B0%E5%8C%BA%E4%BA%88%E9%81%B8/

「同年センバツ参加校による地区予選免除」と「前年秋の上位校免除」は別の契約。2026の推薦枠1校を固定定数にせず、ゲーム年度の完全参加名簿から神奈川県内の学校を抽出する。

## 2. 実装

### 2-1. センバツ32校MAINを年度共通セーブへ追加

既存phase2_engine/career_multi_preview_checkpoint.pyにentry_mode=national_invitational_main_v1を追加。

- 対象はCMP000001のみ、32校の学校IDをすべて明示する。未知校・重複・不足・他大会への誤適用・地区グループ指定・前年秋結果の流用は拒否。
- 既存2026大会マスターと2026日程からの**ゲーム内2027仮日程**で、実際のTournamentEngineとAbilityMatchResolverで試合を実行。2027進級済み選手の保存ロスターが全校分必要。
- 同じcareer_multi_previews/2027.jsonの試合日順進行、同じhistorical_matches.sqlite3へのA方式履歴追記、シード未付与、決定論的再開を使用する。
- 参加32校は**ゲームのためユーザー／テストが明示選択したリスト**であり、センバツの選考委員会の選考シミュレーションを実施した結果ではない。

### 2-2. 完全参加名簿の独立保存・整合監査

新規phase2_engine/career_invitational_manifest.py：CareerInvitationalManifestService

- record(slot,year)：2027年度共通セーブに国大会CMP000001が登録済みで、32校分の入力・完全ロスター・大会方式・保存済みセーブを検証し、career_invitational_manifests/2027_CMP000001.jsonへ記録する。
- JSONはsource_plan_fingerprint、32校・そのSHA256、前年度封印台帳SHA256、年度・大会ID、仮参加校の由来などを保存。二重登録は同一内容のときだけ許容する。
- audit_kanagawa(slot,year)：再ロード時に年度共通セーブと独立名簿が一致することを再確認し、神奈川pcode14の全参加校を抽出する。学校数0も**完全32校名簿が存在するときに限り**判断できる。
- 独立名簿が未作成の場合はStage43G-6と同じrequires_same_year_verified_invitational_participantsを返し、「出場0校」には変換しない。
- future_official_participants_confirmed=false、automatic_bypass_enabled=false、runtime_ready=false、main_seed_school_ids=[]を維持。資料未確認のシード権・2027公式選考・県大会本戦の自動起動は一切解禁しない。
- 既存のentry_mode無し年度チェックポイントの正規化・過去のセーブ再計算は行わない。

## 3. テスト

tests/test_stage43g8_senbatsu_manifest.py：
1. 参加名簿なしは未確認。全国32校の大会が未登録なら0校の推定禁止。
2. ゲーム参加32校のうち神奈川2校という試験入力で2校を特定し、地区予選からの免除対象として監査。ただしまだMAINへ自動追加しない。
3. 完全32校名簿に神奈川0校という試験入力がある場合は「0校」を正しく確定できる。
4. 31校・重複・方式偽装・グループ指定・誤った前年ソースを開始前に拒否する。
5. センバツの試合を2027年度の同じSQLiteへ個人成績込みで保存し、再ロード後の名簿と2026封印履歴を確認する。
6. JSON名簿・年度入力の改変、競合時は資格認証しない。
7. 他大会しかない年度からセンバツ出場者数0を推定しない。

## 4. 次工程

**Stage43G-9**：神奈川春CMP000095のFMT006（3〜4校リーグ＋補充代表決定戦）を2027年の明示的な地区所属・学校・継続ロスターに接続。Stage43G-8の名簿監査で確定した県内センバツ出場校だけを予選免除し、4地区からの代表とMAINへ統合。年度共通セーブ、A方式試合記録、途中再開を検証する。

引き続き神奈川春の代表2校・関東全17校の完全なゲーム内実資格確定、全国162大会の自動実行、正式GUI、翌年実在の大会資格は未完成として扱う。
