# Oak Advisor

A free, fully local shop helper for **Oaken Tower**. Press a key during the shop phase and it
reads your screen (gold, hearts, wins, the 7 shop items with their pack tags and prices, your
tower and storage), then tells you what to **buy**, what to **freeze**, and whether to
**refresh** or **level up**. Advice shows on a panel for your second monitor and as an overlay
on top of the game (green box = buy, blue box = freeze).

Nothing leaves your PC: no API, no account, no cost.

## Get the app (same flow as Touch Grass)

1. Make a new GitHub repo and upload everything in this folder (including `.github/`).
2. Open the **Actions** tab → **Build OakAdvisor** → it runs on every push (or press *Run workflow*).
3. When it's green, download **OakAdvisor-windows** from the run's *Artifacts*, unzip it anywhere,
   and run `OakAdvisor\OakAdvisor.exe`.

To run from source instead: `pip install -r requirements.txt` then `python main.py`.

## Game settings

- Display mode **Borderless Windowed** (or windowed). Exclusive fullscreen can't be captured or overlaid.
- Any resolution works as long as the game keeps its 16:9 layout (your 3440×1440 is fine — the
  black side bars are expected).

## Keys

| Key | What it does |
|---|---|
| **F8** | Scan the shop and give advice |
| **F9** | Learn the item under your mouse (hover it so its tooltip is open, then press F9) |
| **F10** | Overlay on/off |

Keys work while the game has focus. Change them in **Settings** if something else uses them.

## Teaching it items (the first few runs)

The app reads pack tags, prices, sales and the game's purple "combines with what you own" glow on
day one, so it gives useful advice straight away. To know *which* item is which, it learns item
pictures as you play:

- **Hover an item and press F9.** It reads the tooltip (name, rarity, cooldown, damage, effect
  text) and remembers the picture. Works in the shop, on tower tiles and in storage.
- No tooltip? Click any "Unknown" card in the panel and type the name.
- Once it has seen an item it keeps adding new looks of it automatically.
- Open **Item library** to give items a rating (S best → D worst), fix packs, or mark potions.
  Ratings are the biggest lever you have on the advice.

Your library lives in `%APPDATA%\OakAdvisor` (items.json + icons folder) — back it up if you like.

## How it decides

Each shop item gets a score:

- your rating for the item (unrated items get a middling score)
- **+** fits your main build direction (worked out from your tower items, or from what it saw you
  buy this run) — **−** if you're committed elsewhere
- **+** combines with an item you own (bigger if that item is already upgraded)
- **+** empty tower slots (fill the board early), packs you like, sale price, rarity

It buys the best items it can afford above the buy threshold, freezes a strong item you can't
afford, then spends the rest: **level up** when your hearts are healthy, **refresh** when they're
low or nothing fits. Thresholds and your favourite packs (Dragon, Witch, Moon, Dark, Arcane) are in
**Settings**.

It's a coach, not a bot — it never clicks anything for you.

## Checking it without the game

`python tools/test_frames.py screenshot.png` prints what it reads from a saved screenshot.
`python tools/selftest.py` checks reading against the two sample screens in `tests/`.
