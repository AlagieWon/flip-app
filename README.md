# Flip

**Small moments. Big swings.**

Flip finds the single play that flipped a game: the moment the win probability swung hardest. It shows that moment as a chart you can swipe through, vote on and share.

**Live demo:** https://alagiewon.github.io/flip-app/

<p>
  <img src="screenshots/01-flips.png" width="200" alt="Flips feed">
  <img src="screenshots/02-lounge.png" width="200" alt="Match Lounge">
  <img src="screenshots/03-flip-deck.png" width="200" alt="Swipe deck of a game's turning points">
  <img src="screenshots/04-share-card.png" width="200" alt="Share card">
</p>

## What it does

- **Flips feed.** A swipeable feed of turning points: missed calls, flags, subs and big plays. Each one says how much it moved the win chance.
- **Match Lounge.** Live and finished games show the win-probability line. Gold marks the takeover after the flip, and grey is the game before it.
- **Swipe deck.** Open any game and swipe through every turning point in order. The deck also shows missed chances, with an estimate of what could have been.
- **Two numbers everywhere.** The **swing**, meaning how many points of win chance a play moved, and **% of fans who agree** it flipped the game.
- **Share cards.** Every flip exports as an image built for X, TikTok and group chats.

## How the data works

Real games are tracked from public play-by-play feeds:

- `tools/pull_live.py` pulls ESPN win probability and plays, plus MLB Stats API hit data (exit velocity, distance and pitch location). It then detects turning points automatically.
  - Near-homers: a ball hit 330 ft or more and caught.
  - Missed ball/strike calls, measured against the strike zone.
  - Errors, rule calls and big swings.
  - Stranded rallies: missed chances to flip the game.
- `tools/wpmodel.py` is a small baseball win-probability model built from run-expectancy and scoring-probability tables. It's used to estimate what-if scenarios on top of ESPN's line, for example "a two-run single here takes it to ~73%".
- Each play's status updates as the game goes on. A big swing is marked **held** if the advantage lasts, or **erased** if it's later undone.

Games without a live feed use illustrative win-probability lines, and the app labels them that way.

## Tech

- The app is a single HTML file with vanilla JavaScript, CSS, and SVG/Canvas charts. There are no frameworks or build step.
- The data pipeline is Python with no dependencies.
- It is designed mobile-first and runs full screen on a phone.

## Status

This is a prototype and personal project. Votes are stored in the browser.

Built by Alagie · [@flippdodds](https://x.com/flippdodds) · prototyped with Claude as a coding partner.
