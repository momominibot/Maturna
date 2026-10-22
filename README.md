# Maturna · Pregnancy Companion

A single-file pregnancy tracking app built on the **Rhythme / Ovumind design system**
(pastel lavender + peach, Newsreader serif + Manrope sans, 390px phone frame).

## Run it
```bash
python3 -m http.server 8765
# open http://localhost:8765
```
Or just double-click `index.html` — it is fully self-contained.

## Features
- **Home** — EDD countdown hero, current week, fruit-size comparison, trimester progress %, quick actions
- **Grow** — all 40 weeks with fruit/vegetable size, length, weight, baby development, what's happening for you
- **Eat** — trimester-switched foods to enjoy / avoid / top nutrients (folate, DHA, iron, calcium)
- **List** — tap-to-check checklists: hospital bag, baby essentials, postpartum recovery (progress bar, persisted)
- **Feed** — breastfeeding log (side + minutes) + a timed 60-min power-pump session (pump 10 / rest 10 × 3)

## Test
```bash
pip install playwright==1.63.0 && playwright install chromium
python3 tools/smoke.py                # this checkout
python3 tools/smoke.py --root ../old  # any other checkout
```
Headless Chromium at 390x844 in Asia/Singapore with a fixed clock: due dates for weeks 2, 20 and 38,
appointments, feed dates, swipe, contraction timer, nursery, yoga and the desktop frame. Exits 1 on any failure.

## Tech
- Static HTML/CSS/JS, no build step
- LocalStorage for EDD, checklist state, and today's feed log
- Google Fonts (Newsreader + Manrope) + Material Symbols Outlined
- Seedream 5.0 Pro illustrations (hero + logo)
- Same CSS tokens, phone frame, and bottom-nav pattern as `momominibot/rhythme`

## Next steps
- Deploy to Vercel (same as Rhythme)
- Add a Capacitor wrapper for iOS
- Hook up Volcengine TTS for a warm weekly audio note
