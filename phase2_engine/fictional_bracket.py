"""Stage117 generic single-elimination structure: pure data, no DB or driver.

Placement takes a caller's scenario RNG; the graph only says which feeder
winners meet. The product bracket library resolves all games at once and is
deliberately not used for incrementally saved fictional tournaments.
"""
from dataclasses import dataclass

MIN_SIZE, MAX_SIZE = 4, 32


def seed_positions(size):
    """Standard seed order: 1 and 2 at opposite ends, then halves recursively."""
    order = [1]
    while len(order) < size:
        n = len(order) * 2
        order = [x for s in order for x in (s, n + 1 - s)]
    return tuple(order)


def plan_slots(entries, seeds, rng, size):
    """Declared seeds at standard positions, others shuffled, BYEs to top seeds."""
    entries = tuple(entries)
    n = len(entries)
    if (type(size) is not int or not MIN_SIZE <= size <= MAX_SIZE or size & (size - 1)
            or not 2 <= n <= size < 2 * n or len(set(entries)) != n):
        raise ValueError('bracket size/entries unsupported')
    seeded = dict(seeds)
    if (len(seeded) != len(seeds) or len(set(seeded.values())) != len(seeded)
            or not set(seeded) <= set(entries) or any(not 1 <= s <= n for s in seeded.values())):
        raise ValueError('declared seeds invalid')
    order = seed_positions(size)
    slots = [None] * size
    # Seed number k sits at order.index(k); BYE number b pairs with seed b.
    for tid, number in seeded.items():
        slots[order.index(number)] = tid
    byes = size - n
    for number in range(1, byes + 1):
        position = order.index(number)
        partner = position ^ 1
        if slots[partner] is not None:
            raise ValueError('BYE position occupied')
        slots[partner] = 'BYE'
    rest = [t for t in entries if t not in seeded]
    rng.shuffle(rest)
    free = [i for i, s in enumerate(slots) if s is None]
    for i, tid in zip(free, rest):
        slots[i] = tid
    return tuple(None if s == 'BYE' else s for s in slots)


@dataclass(frozen=True)
class Game:
    sequence: int
    round_no: int
    position: int
    # Feeders: ('slot', i) or ('game', sequence) or ('bye', team_id).
    feeders: tuple


class Bracket:
    """Graph of actual games. A slot paired with None is a BYE, not a game."""

    def __init__(self, slots):
        slots = tuple(slots)
        size = len(slots)
        if not MIN_SIZE <= size <= MAX_SIZE or size & (size - 1):
            raise ValueError('bracket size unsupported')
        teams = [s for s in slots if s is not None]
        if len(teams) != len(set(teams)) or len(teams) * 2 <= size:
            raise ValueError('bracket slots invalid')
        if any(a is None and b is None for a, b in zip(slots[::2], slots[1::2])):
            raise ValueError('double BYE')
        self.slots, self.size = slots, size
        self.rounds = size.bit_length() - 1
        games, byes, current = [], [], []
        for i in range(0, size, 2):
            a, b = slots[i], slots[i + 1]
            if a is None or b is None:
                team = a if b is None else b
                byes.append(team)
                current.append(('bye', team))
            else:
                current.append(('pair', ('slot', i), ('slot', i + 1)))
        number = 0
        for round_no in range(1, self.rounds + 1):
            following = []
            for position, item in enumerate(current):
                if item[0] == 'bye':
                    following.append(item)
                    continue
                number += 1
                games.append(Game(number, round_no, position, item[1:]))
                following.append(('game', number))
            if len(following) > 1:
                current = [('pair', following[i], following[i + 1]) for i in range(0, len(following), 2)]
        self.games, self.byes = tuple(games), tuple(byes)

    def game(self, sequence):
        return self.games[sequence - 1]

    def _feeder(self, feeder, results):
        kind, value = feeder
        if kind == 'slot':
            return self.slots[value]
        if kind == 'bye':
            return value
        if value > len(results):
            return None
        return results[value - 1].winner_id

    def pair(self, sequence, results):
        """Participants from actual previous winners; None if not yet decided."""
        a, b = (self._feeder(f, results) for f in self.game(sequence).feeders)
        return None if a is None or b is None else (a, b)

    def eliminated_round(self, results):
        out = {}
        for result, game in zip(results, self.games):
            out[result.loser_id] = game.round_no
        return out

    def ranks(self, results):
        """Standard single-elimination ranks; only after the final is saved."""
        if len(results) != len(self.games):
            return []
        final = results[-1]
        rounds = self.eliminated_round(results)
        rows = [(1, final.winner_id)]
        for tid, round_no in rounds.items():
            rows.append((2 ** (self.rounds - round_no) + 1, tid))
        return sorted(rows, key=lambda r: (r[0], r[1]))
