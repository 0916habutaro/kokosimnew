"""セーブごとの学校評判。確定した大会を一度だけ、翌4月の入学前に反映する。"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
import math
from pathlib import Path
from statistics import NormalDist

from phase2_engine.randomness import rng_for
from .ability_config import load_config
from .school_reputation import reputation_for


def _shares(scores):
    order = sorted(scores, key=lambda sid: (scores[sid], sid))
    return {sid: (i + 0.5) / len(order) for i, sid in enumerate(order)}


class AnnualReputation:
    def __init__(self, root: str | Path, seed: int, first_year: int = 2026):
        root = Path(root).resolve()
        initial = reputation_for(str(root))
        self.config = load_config(
            root / 'config/abilities/annual_reputation_v1.json',
            expected_config_id='annual_reputation_v1',
        ).payload
        if not 0 < self.config['carry'] < 1:
            raise ValueError('annual reputation carry must be between 0 and 1')
        if not 0 < self.config['max_annual_change_z'] < math.inf:
            raise ValueError('annual reputation change limit must be positive and finite')
        for weights in ('competition_weights', 'finish_points'):
            if any(not 0 <= v < math.inf for v in self.config[weights].values()):
                raise ValueError(f'annual reputation {weights} must be nonnegative and finite')
        self.rank_labels = initial.config['rank_labels']
        self.mean, self.stddev = initial._mean, initial._stddev
        self.seed = seed
        self.first_year = self.updated_year = first_year
        # z は順位の正規変換。初年度は従来の program_z と完全に同じ。
        self.values = {sid: initial.program_z(sid, seed) for sid in initial.school_ids}
        self.intake_by_year = {first_year: dict(self.values)}
        self.counted: set[tuple[int, str]] = set()
        # 完了日、学校ごとの点。年度が閉じて大会の状態を手放しても残る。
        self.pending: dict[tuple[int, str], tuple[str, dict[str, float]]] = {}

    def program_z(self, school_id: str, entry_year: int) -> float | None:
        year = max(self.first_year, entry_year)
        if year not in self.intake_by_year:
            raise ValueError(f'reputation for intake {year} is not fixed yet')
        return self.intake_by_year[year].get(school_id)

    def rank(self, school_id: str) -> str:
        share = _shares(self.values).get(school_id)
        if share is None:
            return ''
        return next(label for label, minimum in self.rank_labels if share >= float(minimum))

    def collect(self, seasons) -> None:
        """予選も含め大会全体が確定してから採る。試合別の点との二重加算はしない。"""
        for year, season in sorted(seasons.items()):
            for cid, scheduled in sorted(season.competitions.items()):
                key = (year, cid)
                if key in self.counted or key in self.pending or not scheduled.is_complete:
                    continue
                run = scheduled.to_competition_run()
                outcome = run.outcome
                if outcome is None:
                    continue
                competition = season.repo.competitions[cid]
                weight = self.config['competition_weights'][competition['competition_type']]
                points = defaultdict(float)
                finish = self.config['finish_points']
                # 順位決定戦・予選の試合数や不戦勝によらず、最終到達点を1回だけ使う。
                for sid in run.entrant_school_ids:
                    points[sid] = float(finish['appearance'])
                for sids, label in (
                    (outcome.quarterfinalist_school_ids, 'best8'),
                    (outcome.semifinalist_school_ids, 'best4'),
                    ([outcome.runner_up_school_id], 'runner_up'),
                    ([outcome.champion_school_id], 'champion'),
                ):
                    for sid in sids:
                        if sid:
                            points[sid] = max(points[sid], float(finish[label]))
                completed = [m.completed_on for m in scheduled.matches.values() if m.completed_on]
                if not completed:
                    continue
                self.pending[key] = (max(completed), {sid: p * weight for sid, p in points.items()})

    def update(self, day: date) -> bool:
        if (day.month, day.day) != (4, 1) or day.year <= self.updated_year:
            return False
        if day.year != self.updated_year + 1:
            raise ValueError('reputation must be updated in consecutive school years')
        totals = {sid: 0.0 for sid in self.values}
        for key, (completed, points) in list(self.pending.items()):
            if completed >= day.isoformat():
                continue
            for sid, value in points.items():
                if sid in totals:
                    totals[sid] += value
            self.counted.add(key)
            del self.pending[key]
        # 同点内の順は能力と独立した固定乱数。名門への同点優遇を残さない。
        order = sorted(totals, key=lambda sid: (
            totals[sid], rng_for(self.seed, f'annual_reputation:tie:{sid}').random(), sid,
        ))
        carry = float(self.config['carry'])
        limit = float(self.config['max_annual_change_z'])
        normal = NormalDist(self.mean, self.stddev)
        for index, sid in enumerate(order):
            target = normal.inv_cdf((index + 0.5) / len(order))
            change = (target - self.values[sid]) * (1 - carry)
            self.values[sid] += max(-limit, min(limit, change))
        self.updated_year = day.year
        self.intake_by_year[day.year] = {
            sid: normal.inv_cdf(share) for sid, share in _shares(self.values).items()
        }
        return True
