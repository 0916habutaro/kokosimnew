# Stage43G-119-CI-1：文書変更時の長時間CI重複削減と検証契約

- 対応Issue: [#297](https://github.com/0916habutaro/kokosimnew/issues/297)
- 起点main: `8ac54d55106196c1eff741999f72e1511f9c6d1e`（Stage119-B PR #296マージ後）
- **Stage119-C（v3保存実装）とは独立**。新規保存エンジン、SQLite schema、既存試合テスト、所要時間上限は変更しない。

## 背景・範囲

Stage119-B（日本語設計書だけの変更）ではPRとmainへのマージ後の両方で約100分の全unittestとLinux/Windowsの実規模監査が動作した。設計文書のみの変更が実行コードへ影響しないことを限定的に利用し、**最も長い3ワークフローの4 job**に対してdocs-only fast pathを導入する。その他のCIの既存条件・実行範囲は変更しない。

|ワークフロー|従来の長時間ジョブ|docs-onlyの動作|
|---|---|---|
|`python-tests.yml`|全unittest（120分上限）、関東17校E2E|各ジョブの短いrouting単体テストのみ。フル計時JSONの捏造・アップロードなし|
|`stage118-fictional-bracket32.yml`|架空16/32チーム実規模監査 Linux/Windows|両OSで短いrouting単体テストのみ。実監査artifactなし|
|`windows-yamanashi-annual-rosters.yml`|年次保存・故障復旧・旧版互換の連続7監査|routing単体テストのみ。実監査artifactなし|

各ジョブ名を保持したままステップで分岐するため、**文書だけのPRでもCIチェックは成功/失敗として報告**される。workflows自体を `paths-ignore` で非起動にしてrequired checkをpendingに残す設計ではない。

## 変更検出とfail-closed

`tests/ci_change_scope.py` を標準ライブラリだけで実装する。GitHubの信頼できるイベントSHAで比較する。

- PR：イベントの `pull_request.base.sha` と `pull_request.head.sha`
- main push：イベントの `before` と `github.sha`。削除・改名も見落とさない `git diff --no-renames --name-only -z --diff-filter=ACDMRTUXB` を利用。
- docs-only許可：ルートの `README.md`／`CHANGELOG.md`／`CONTRIBUTING.md` と、`docs/**` 配下の `.md`／`.markdown`／`.rst` のみ。空の差分・不明なイベント・比較失敗・SHA不正はfull。
- **コード、tests、config、.github/workflows、CSV・JSON・SQLite、マスター、マージ衝突、複数種類が混ざる変更はすべてfull**。
- `workflow_dispatch` は強制full。branchがmain以外のpushもfullに倒す。
- `GITHUB_OUTPUT` に `docs_only=true/false` を出力。 `GITHUB_STEP_SUMMARY` にルートと理由を表示。
- 検証対象の既存CIコマンド・引数、環境変数、既存テスト数、skip条件、120分timeoutは維持。

## 回帰・証拠

`tests/test_ci_change_scope.py` に、文書・非文書・混合変更、比較不可・不正SHA、manual、変更なし、`git diff -z` の名前処理と失敗、3ワークフローの配線・元の長時間監査コマンドが残ることを合成データで検証する。

このPRでは `tests/` と `.github/workflows/` を変更しているため **docs-onlyには該当しない**。PRとマージ後mainの両方で従来の長時間全件CIを実行して動作を確認し、CI時間改善は**後続の本物のdocs-only PRでのみ実測する**。GitHub CIと個人Windows端末の結果を混同しない。

## 既知の制約・後続CI-2

- docs-onlyで短縮するのは上記3ワークフロー。ほかのワークフローに過剰な改変はしない。不要なランナー起動の最適化は後続で検討。
- mainのbranch protection/required checksは現在未設定。**コードPRのマージ前・マージ後の全件検証は本工程では省略しない**。重複を安全に減らすCI-2では、保護されたmain、検証headの同一性、直接pushの制御、統合スモーク、定期全件監査を別PRで設計する。
- 定期監査自動起動も今回導入しない。処理が変わるCI-2の前に、レビュー・独立検証を必須とする。

## 運用

新規専用ブランチから日本語PRでレビューを受ける。CIが全成功しても**未マージ・auto-merge無効**とし、ユーザーの明示承認後にのみmainへ反映する。
