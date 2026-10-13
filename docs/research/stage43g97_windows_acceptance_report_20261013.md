# Stage43G-97 実装・検証報告

Issue #249、PR #248マージ後のmainから`stage43g97-windows-acceptance`で実施。日本語設計書の接続一覧・不足一覧が今回のゲーム現状評価である。Windows専用・個人利用・配布なしの方針に合わせ、主要受入をWindowsネイティブPython3.12/Tkにした。

## 変更前後

変更前は新規/試合保存/ロードと履歴Tkを、それぞれのStageの検証で確認していた。Stage97では新規模擬ゲームを実サービスで生成し、別cwd・別プロセス再起動から履歴モデル/Tkへ結ぶ小規模受入を追加した。manual/autosaveそれぞれ6→7試合、封印と翌年台帳登録後の過年度参照を検査する。

製品ソースは変更していない。調査でロスター・大会結果・学校/選手読取の一部SQLite接続がGCに依存することを確認した。製品側のclose追加はStage94の固定338ファイル互換性digestを変更し、既存export/verifyを拒否するため採用しなかった。固定カタログや旧backup候補を変更せず、今回の新fixtureには既存Stage94の`owned_sqlite_handles`で明示解放を適用する。製品側のhandle寿命は未解決で、互換性設計と合わせた次工程の優先課題として報告する。

## 検証と証拠の見方

- `tests/stage43g97_audit.py`のheadless 3件：別プロセス生成/保存/再生、全試合詳細・学校勝敗・代表打者/投手の独立集計、全fileの読取不変、破損拒否と原本bytesからの再試行、native接続をfixture scope終了時に明示解放、rollback/終了後rename。
- 実Tk 1件：表示window・Tkイベントループ、年度/学校/スコア/イニング/打撃/投手/選手表示、誤slot拒否/再読込、終了とroot再生成2回。Windows CIは`--require-windows`を必須にし、skipが1件でもあれば失敗する。
- 全Python3.12 unittest、関東17校E2E、影響した既存backup/履歴/保存回帰は既存Checksで維持する。今回の新CIは毎PRにWindows小規模必須受入とLinux補助受入を実行する。Windows全suiteの週次/手動実行は設計提案に留める。
- ローカルLinux headlessは3件skip 0で合格。全suite・Windows・Linux実Tkの確定結果は**PR最新headのChecksとworkflow artifacts**を証拠とする。公開JSONはテスト件数・成否・OS・経路指標だけで、private SHAや保存パスを含めない。
- このCloud環境のローカルXvfbは表示ソケットをbindできずTk起動失敗。GUI合格の根拠はCIの実Tk結果であり、ローカルGUI操作の合格とはしない。

## 既存データ保護・保証範囲

標準`out/saves`では既存saveを検出していない（0件）。別の作業環境出力領域にはsave相当4ファイルが存在した。由来を未確認のため実ユーザーsaveとも模擬saveとも断定しない。内容・ロード・復元は未検証、試験入力に使っていない。privateパス/SHA一覧は公開しない。

本試験は新規TemporaryDirectoryだけで実施する。fixture内の接続管理を製品側のhandle解放保証に見せかけない。自己生成試合runtimeを期待値として保存/閲覧のスコア・詳細・ID出典を検証するため、保存DBをそのまま期待値として採用しない。過去記録の読取時は全file不変を確認し、2027登録後も2026試合が維持されることを確認する。

新しい正式ゲームUI、本番restore/import/activation、migration、履歴削除は追加していない。ロスター/大会結果は今回のtest harnessが明示的に保存しており、製品サービスの統合未完成を隠さない。8校固定plannerの単大会を全国・複数大会careerや100/200年実進行の証明にはしない。翌年登録は翌年の試合開始ではない。人によるWindows実機確認は未実施。

Stage94 export/verify API、Stage95/96 fixture用検証を維持。Option A全件保持・年数無制限を変更せず、配布用機能を追加していない。次工程は設計書の優先度表に従い、統合ゲーム導線・保存ライフサイクルをレビューしてから正式GUI範囲を決める。

PRは最新headの必須Checksすべての成功を確認してからレビュー待ちとし、マージ/auto-mergeしない。Checks結果と実機確認の違いを日本語PRおよび完了報告にも記載する。
