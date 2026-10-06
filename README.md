# KokoSimNew / ココシミュNew

高校野球の大会構造・日程・試合進行を扱うゲーム用データ／エンジンの管理リポジトリ。

## 現在地
- Phase 1: 完了（47都道府県、学校 3,746、硬式野球部 3,746）
- Phase 2: Stage 12M完了（Stage 12M-1〜8で夏地方49大会すべてを個別実試合日へ詳細化）
- Stage 12G: 全国47都道府県の春秋94大会の日程を `season_calendar.csv` に正式反映済み
- 県春秋94大会の日程: official_schedule 94 / research_pending 0
- Stage 12G初回試合日: 累計809日。Stage 12I再照合で福岡秋10/14を追加し、現在のmasterは810日相当
- 夏地方大会の個別試合日: 49 / 49大会を実績化済み（Stage 12M-1〜7 累計511日＋12M-8 118日＝累計629日、残り0大会）
- 秋季実績再照合: 2026-10-06 EODに県大会6件を実績更新。埼玉は完了、県大会残件18・地区大会残件9。次回チェックは10/7の北海道・福岡

## ディレクトリ
- `data/master/` 学校・加盟校・出典の基礎マスター
- `data/areas/` 地区区分・学校所属
- `data/competitions/` 大会・stage・進出・seed・format・地域大会接続
- `data/schedules/2026/` 2026年日程マスター／試合日
- `data/sources/` Phase 2調査出典
- `phase2_engine/` 大会・シーズン共通エンジン
- `tests/` 回帰テスト
- `audits/` Phase/Stage別の監査・manifest・validation
- `archive/snapshots/` 移管元の完成ZIP（復旧用）

## 実行
```bash
python -m unittest discover -s tests -v
python -m phase2_engine.season_cli --data-dir data --year 2026 --seed 2026100501
python -m phase2_engine.reconciliation_cli \
  --queue audits/phase2/stage12i/stage12i_autumn_reconciliation_queue_20261006.csv \
  --as-of 2026-10-06 \
  --output audits/phase2/stage12i/stage12i_recheck_status_20261006.csv
```

## 正本ルール
展開済みの `data/`, `phase2_engine/`, `tests/` を正本とする。`archive/snapshots/` のZIPは復旧用で、日常編集には使用しない。

## 次工程
Stage 12M完了。秋季は2026-10-06 EOD再照合で埼玉・京都・大阪・岡山・広島・福岡の当日分を実績化済み。県大会残件18、Stage12J地区大会残件9。次回は10/7の北海道秋季大会開幕と福岡準々決勝残り2試合を終了後に再照合する。明治神宮大会1件は10/17抽選後に更新する。
