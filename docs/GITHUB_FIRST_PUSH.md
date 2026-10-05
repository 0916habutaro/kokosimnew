# GitHub 初回投入手順

このフォルダをリポジトリのルートとして使用する。

```bash
git init
git add .
git commit -m "chore: consolidate KokoSimNew through Stage 12G Tohoku"
git branch -M main
git remote add origin <GitHub repository URL>
git push -u origin main
```

## 初回投入前の確認

```bash
python -m unittest discover -s tests -v
python -m phase2_engine.season_cli --data-dir data --year 2026 --seed 2026100501
```

期待値:
- unit tests: 74/74 PASS
- prefectural competitions: 94/94 PASS
- prefectural calendar gaps: 79
- warnings: 0

`archive/snapshots/` は復旧用であり、通常の編集対象は展開済みの `data/`, `phase2_engine/`, `tests/`。
