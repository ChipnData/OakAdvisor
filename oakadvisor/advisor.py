"""The 'brain': turns a GameState into ranked advice.

Plain rules you can tune in Settings. The ideas come from common Oaken Tower
strategy: fill your tower early, commit to one pack direction, feed copies into
upgrades, protect your hearts, and only level up when the board can survive.
"""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass, field

RATING_BASE = {"S": 44, "A": 34, "B": 24, "C": 14, "D": 4, "": 20}
RARITY_BONUS = {"Common": 0, "Rare": 5, "Epic": 10, "Legendary": 16}


@dataclass
class Settings:
    favorite_packs: list = field(default_factory=lambda: ["Dragon", "Witch", "Moon", "Dark", "Arcane"])
    buy_threshold: int = 45        # score an item needs before it's worth buying
    freeze_threshold: int = 58     # good item you can't afford -> freeze it
    safe_hearts: int = 6           # at or above this you can afford to be greedy (level up)
    commit_weight: float = 4.0     # pack weight at which you're "committed" to a direction
    tower_slots: int = 6


@dataclass
class SlotAdvice:
    index: int
    score: int
    reasons: list
    action: str = ""               # "buy", "freeze", "skip"


@dataclass
class Advice:
    headline: str
    steps: list
    slots: dict
    direction: list
    notes: list


class RunTracker:
    """Remembers what you bought this run (from one scan to the next), so the advisor
    knows your build direction even before it has learned your items' names."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.packs = Counter()
        self.bought = []
        self.last = None

    def update(self, st):
        if not st.in_shop:
            return
        last = self.last
        if last is not None:
            new_run = ((st.day is not None and last.day is not None and st.day < last.day) or
                       (st.wins is not None and last.wins is not None and st.wins < last.wins))
            if new_run:
                self.reset()
            elif st.day == last.day and st.gold is not None and last.gold is not None:
                spent = last.gold - st.gold
                for a, b in zip(last.shop, st.shop):
                    if not a.empty and b.empty and a.price and spent >= a.price - 1:
                        spent -= a.price
                        self.bought.append((a.name, tuple(a.packs)))
                        for p in a.packs:
                            if p != "Neutral":
                                self.packs[p] += 1.0
        self.last = st


def _owned(state, lib, tracker):
    names, tiers, packs = Counter(), {}, Counter()
    known_owned = 0
    for o in state.tower + state.storage:
        if not o.name:
            continue
        names[o.name] += 1
        tiers[o.name] = max(tiers.get(o.name, 1), o.tier)
        it = lib.items.get(o.name)
        if it and not it.consumable:
            known_owned += 1
            w = (1.0 * o.tier) if o.where == "tower" else 0.6
            for p in it.packs:
                if p != "Neutral":
                    packs[p] += w
    if tracker is not None and known_owned < len(state.tower):
        for p, w in tracker.packs.items():   # fill the gap with what we saw you buy
            packs[p] += w
    return names, tiers, packs


def _score(slot, state, lib, cfg, names, tiers, primary, secondary, committed, free_slots):
    it = lib.items.get(slot.name) if slot.name else None
    reasons = []
    rating = (it.rating if it else "") or ""
    s = RATING_BASE.get(rating, 20)
    if rating:
        reasons.append(f"rated {rating}")
    item_packs = set(slot.packs or (it.packs if it else []))

    if it and RARITY_BONUS.get(it.rarity):
        s += RARITY_BONUS[it.rarity]
        reasons.append(it.rarity)

    if slot.upgrade_glow or (slot.name and names.get(slot.name)):
        s += 24 + 8 * max(0, tiers.get(slot.name, 1) - 1)
        reasons.append("combines with one you own")

    if primary and primary in item_packs:
        s += 25
        reasons.append(f"fits your {primary} build")
    elif secondary and secondary in item_packs:
        s += 12
        reasons.append(f"fits {secondary}")
    elif "Neutral" in item_packs:
        s += 6
        reasons.append("Neutral, fits anything")
    elif committed and item_packs:
        s -= 15
        reasons.append("off your build")

    fav = item_packs & set(cfg.favorite_packs)
    if fav and not (primary and primary in item_packs):
        s += 6
        reasons.append(f"{'/'.join(sorted(fav))} is a pack you like")

    if free_slots > 0 and not (it and it.consumable):
        bonus = min(24, 6 * free_slots)
        s += bonus
        reasons.append("tower has empty slots")

    if slot.sale:
        s += 5
        reasons.append("on sale")
    if it and it.consumable:
        s -= 8
        reasons.append("potion")
    hearts = state.hearts if state.hearts is not None else 10
    if hearts <= 3 and it and it.damage:
        s += 6
        reasons.append("power now, hearts are low")
    return int(s), reasons


def _label(slot):
    nm = slot.name or "the"
    pk = "/".join(slot.packs) if slot.packs else "?"
    row = "top" if slot.index < 4 else "bottom"
    pos = slot.index + 1 if slot.index < 4 else slot.index - 3
    what = f"{nm} ({pk})" if slot.name else f"the {pk} item"
    return f"{what} — {row} row #{pos}, {slot.price}g"


def advise(state, lib, cfg: Settings, tracker: RunTracker | None = None) -> Advice:
    if not state.in_shop:
        return Advice("Open the shop, then scan.", [], {}, [], list(state.warnings))

    names, tiers, packs = _owned(state, lib, tracker)
    for p in cfg.favorite_packs:          # small nudge toward your packs before anything is owned
        packs[p] += 0.5
    ranked = [p for p, _ in packs.most_common()]
    primary = ranked[0] if ranked and packs[ranked[0]] >= 1.5 else None
    secondary = ranked[1] if len(ranked) > 1 and packs[ranked[1]] >= 1.5 else None
    committed = bool(primary and packs[primary] >= cfg.commit_weight)

    gold = state.gold or 0
    hearts = state.hearts if state.hearts is not None else 10
    reroll = state.reroll_cost if state.reroll_cost is not None else 3
    lvl_cost = state.level_cost if state.level_cost is not None else 4
    free = max(0, cfg.tower_slots - len(state.tower))

    open_slots = [s for s in state.shop if not s.empty and s.price is not None]
    slots = {}
    left = gold
    bought = []
    # greedy: re-score after each pick because every buy fills a tower slot
    remaining = list(open_slots)
    while remaining:
        scored = []
        for s in remaining:
            sc, why = _score(s, state, lib, cfg, names, tiers, primary, secondary, committed, free)
            scored.append((sc, -s.price, s, why))
        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        pick = next(((sc, s, why) for sc, _, s, why in scored if sc >= cfg.buy_threshold and s.price <= left), None)
        if pick is None:
            for sc, _, s, why in scored:
                act = "freeze" if sc >= cfg.freeze_threshold else "skip"
                slots[s.index] = SlotAdvice(s.index, sc, why, act)
            break
        sc, s, why = pick
        slots[s.index] = SlotAdvice(s.index, sc, why, "buy")
        bought.append(s)
        left -= s.price
        free = max(0, free - 1)
        remaining.remove(s)

    steps, notes = [], []
    for s in bought:
        a = slots[s.index]
        steps.append(f"BUY {_label(s)}  ({', '.join(a.reasons[:3])})")
    frozen = sorted([a for a in slots.values() if a.action == "freeze"], key=lambda a: -a.score)
    for a in frozen[1:]:
        a.action = "skip"
    if frozen:
        steps.append(f"FREEZE {_label(state.shop[frozen[0].index])} — strong, but you can't afford it yet")

    if bought and len(state.tower) + len(bought) > cfg.tower_slots:
        notes.append("Tower is full — new buys land in storage; swap out your weakest tile.")

    healthy = hearts >= cfg.safe_hearts
    refresh = False
    if not bought and not frozen:
        if left >= reroll and (not healthy or left < lvl_cost * 3):
            steps.append(f"REFRESH the shop ({reroll}g) — nothing here fits your build")
            refresh = True
        elif healthy and left >= lvl_cost:
            steps.append(f"LEVEL UP — put leftover gold into XP ({lvl_cost}g a click); "
                         f"hearts are healthy ({hearts}), so invest in better shops")
        elif left >= reroll:
            steps.append(f"REFRESH the shop ({reroll}g) — look for a better item")
            refresh = True
    elif left >= reroll:
        if not healthy:
            steps.append(f"Then REFRESH ({reroll}g) with the {left}g left — hearts are low, find power now")
            refresh = True
        elif left >= lvl_cost * 2:
            steps.append(f"Then LEVEL UP with the leftover {left}g")
        else:
            steps.append(f"Then REFRESH ({reroll}g) if you want another look")
            refresh = True
    steps.append("Scan again after refreshing" if refresh else "Then LEAVE SHOP")
    if steps == ["Then LEAVE SHOP"]:
        steps.insert(0, "Nothing worth buying — keep your gold.")

    unknown = sum(1 for s in open_slots if not s.name)
    if unknown:
        notes.append(f"{unknown} shop item(s) not recognised yet — hover one in game and press the Learn key "
                     f"(advice uses pack tags until then).")
    unknown_owned = sum(1 for o in state.tower if not o.name)
    if unknown_owned:
        notes.append(f"{unknown_owned} tower item(s) not recognised — learning them sharpens your build direction.")
    if hearts <= 3:
        notes.append("Hearts are low: favour items that win the next fight over long-term scaling.")
    notes += state.warnings

    direction = [(p, round(packs[p], 1)) for p in ranked[:3]]
    return Advice(steps[0], steps, slots, direction, notes)
