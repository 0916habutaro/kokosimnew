# KokoSimNew / ココシミュNew

高校野球の大会構造・日程・試合進行を扱うゲーム用データ／エンジンの管理リポジトリ。

## 現在地
- Phase 1: 完了（47都道府県、学校 3,746、硬式野球部 3,746）
- Phase 2: Stage 12Hまでの大会構造・共通エンジンを統合済み
- Stage 12G: 全国47都道府県の春秋94大会の日程を `season_calendar.csv` に正式反映済み
- 県春秋94大会の日程: official_schedule 94 / research_pending 0
- Stage 12G試合日: 東北92日＋関東133日＋北信越80日＋東海59日＋近畿117日＋中国66日＋四国67日＋九州・沖縄180日＋東京春15日レコード（累計809日）

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
```

## 正本ルール
展開済みの `data/`, `phase2_engine/`, `tests/` を正本とする。`archive/snapshots/` のZIPは復旧用で、日常編集には使用しない。

## 次工程
Stage 12H完了。東京都春・和歌山秋・愛媛秋の前段予選構造を共通大会エンジンへ反映済み。次工程ではStage 12Gで将来予定として登録した秋季大会日程の実績再照合を行う。
