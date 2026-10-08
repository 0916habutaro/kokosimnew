# Stage 13E-3F-1 Full-season Live E2E Blocker 監査報告

作成日: 2026-10-08

## 実行条件

- year: 2026
- seed: 2026100827
- start: 2026-01-01
- processed through: 2026-12-31
- 仮日付なし
- current repository masterそのまま

## 結果

162大会中:

- complete: 98
- calendar_gap: 46
- blocked: 2
- waiting_dependency: 16

未完了64大会。

完了試合6176。

## 当初想定との差分

当初は

- 47 pending competitionが全てcalendar gap
- downstream waiting 16
- complete 99

を想定した。

E2E結果は異なった。

### 差分1: CMP000095 / CMP000113

神奈川春・愛知春はcalendar gapへ到達せずblocked。

原因:

- ACR000008 / ACR000012
- Senbatsu participant_from_destination_prefecture
- expected=1
- structural Senbatsu bootstrap result countが一致せずFAIL

よって日付調査前にdependency resolution修正が必要。

### 差分2: CMP000079

秋田秋はresearch_pending pre-MAIN rowを持たないが、
MAIN runtimeが1試合calendar gap。

season_calendar注記では8/27〜9/7県大会予選を本大会日程から除外。

competition_stagesはMAINのみ。

前段予選未構造化を最優先で確認すべき。

この1大会が追加blockerとなるためcompleteは98。

## downstream

直接blockerから波及して未materialize:

16大会。

春地区7、秋地区8、Jingu1。

春四国CMP000011のみfeeder spring regionalとして完了。

## 全国大会

- CMP000001 センバツ: complete
- CMP000002 夏甲子園: complete
- CMP000003 神宮: waiting

夏49地方→甲子園chainはlive E2Eで完走。

秋→地区→神宮chainが主blocker。

## 作業優先度

stage calendar 49 rows:

- P0 national: 28
- P1 regional: 20
- P2 local: 1

追加blocker:

- P0 CMP000079 structure review: 1
- P1 CMP000095 dependency fix: 1
- P1 CMP000113 dependency fix: 1

最終action queue:

- P0: 29
- P1: 22
- P2: 1
- total: 52

## CI

初回E2Eで想定差分を検出。

1回目:
- CMP000095がcalendar_gapではなくblocked
- complete expected 99 / actual 98

監査ログを一時出力して全non-complete stateを取得。

その結果CMP000113 blockedとCMP000079 extra calendar gapも確定。

監査分類をblocker origin / action queueへ拡張。

最終:

- Ran 568 tests in 53.286s
- OK

## 判断

Stage 13E-3F-1完了。

次はP0を先に解消する。

特にCMP000079は49 stage research queue外のため、
既存queueをそのまま消化する前に構造確認が必要。
