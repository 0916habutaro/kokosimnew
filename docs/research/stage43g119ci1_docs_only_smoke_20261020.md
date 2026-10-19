# Stage43G-119-CI-1：文書のみ変更の実稼働スモーク検証

- 対象Issue: [#297](https://github.com/0916habutaro/kokosimnew/issues/297)
- 実装済PR: [#298](https://github.com/0916habutaro/kokosimnew/pull/298)（main反映済み）
- 検証起点main: `e4151e0fcb0dc969ec2f3a859c10ce9fa1db568e`
- 本PRの目的：**実際のGitHub Actionsでdocs-onlyルートが選択されるか**を確認すること。結果・所要時間はCI終了後にGitHubの実測から記録する。

## 検証対象と範囲

このPRで追加するのはこのMarkdown文書 **1ファイルのみ**。プログラム、マスターCSV/JSON、SQLite保存形式、`tests/`、`.github/workflows/`、ゲームエンジンには一切手を加えない。

`tests/ci_change_scope.py` の許可規則（`docs/**` 配下のMarkdown/RST）に該当することを、本PRを使って実際に検査する。

## 期待するCI動作（結果未確定）

| ジョブ | docs-onlyなら期待すること |
|---|---|
| Python 3.12 unittest | `Classify CI workload` が `docs-only` を報告し、短い `test_ci_change_scope.py` のみ成功。長時間の `stage43g119_ci_metrics.py` は実行しない |
| 関東17校E2E | 同じroutingテストが成功。17校E2Eの本体は実行しない |
| Stage118架空32チーム実規模（Linux / Windows） | 両OSのroutingテストが成功し、長時間の実規模監査は実行しない |
| Windows年次監査 | routingテストが成功し、保存2027・年間ロスター等の連続監査は実行しない |
| そのほかのワークフロー | 従来どおりの起動条件、実行コマンド、完了結果を維持 |

docs-onlyのジョブでは、実行していない監査のJSON artifactが生成されたかのように扱わない。失敗したジョブがあれば、それは問題として修正・再評価する。

## 受入基準

1. 本PR差分がこの文書1ファイルのみである。
2. docs-only routeを備える3ワークフロー4種（Stage118は2 OS）の実ジョブログに `CI workload: docs-only` が記録され、すべて成功する。
3. その3ワークフローでは重い実監査コマンドが **skipped** となり、軽量ルーティング単体テストが **passed** となる。
4. 他の起動したワークフローにも失敗がなく、予期しない長時間の監査再実行を見落とさない。
5. PRのGitHub Actionsの開始・終了時刻から、docs-onlyジョブの経過時間を実測し、従来PR #298のfull経路と条件差付きで比較する。
6. マージ後main pushでもdocs-only判定が動くことを確認する。未確認の段階で高速化を「実測完了」としない。
7. すべて確認してからIssue #297を完了とし、この検証PR自体も明示承認まで **未マージ・auto-merge無効** で維持する。

## 後続工程との独立性

- **Stage119-C（保存v3実装）** はCodex等で別Issue／別ブランチ／別PRとして行う。
- コードPRのマージ後フルCI削減（CI-2）はbranch protectionやrequired checksの安全設計が必要な後続検討。今回変更しない。
- 未確定の2027公式大会情報は確定扱いにせず、既存セーブ・選手履歴へ影響させない。
