"""End-of-window resolution for tournaments.

Called once per tick from the tick engine. For every open tournament whose
`ends_at_tick` has passed, pick the winner (max kills, earliest registration
breaks ties), credit the prize gold + faction reputation, mark the tournament
closed and stamp every entry with its final status. Idempotent: a closed
tournament is skipped on the next tick.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.actions import _grant_rep, _journal_milestone, _set_hero_gold, _hero_gold
from app.core.models import Hero, JournalEntry, Tournament, TournamentEntry

log = logging.getLogger("world.tournament.close")


def close_due_tournaments(db: Session, current_tick: int) -> list[str]:
    """Close every tournament whose window has ended. Returns the list of
    closed tournament slugs (for tick-loop logging)."""
    due = list(
        db.scalars(
            select(Tournament).where(
                Tournament.status.in_(("open", "in_progress")),
                Tournament.ends_at_tick <= current_tick,
            )
        )
    )
    closed: list[str] = []
    for t in due:
        entries = list(
            db.scalars(
                select(TournamentEntry)
                .where(TournamentEntry.tournament_slug == t.slug)
                .order_by(TournamentEntry.kills.desc(), TournamentEntry.registered_at_tick.asc())
            )
        )
        if not entries:
            t.status = "closed"
            log.info("closed empty tournament %s (no entries)", t.slug)
            closed.append(t.slug)
            continue

        winner_entry = entries[0]
        winner: Hero | None = db.get(Hero, winner_entry.hero_id)

        # Pay out prize to winner
        if winner is not None:
            _set_hero_gold(winner, _hero_gold(winner) + int(t.prize_gold or 0))
            if t.prize_faction and t.prize_faction_amount:
                _grant_rep(winner, t.prize_faction, int(t.prize_faction_amount), db=db)
            _journal_milestone(
                db, winner,
                text=(
                    f"Won {t.name}! {winner_entry.kills} kills · "
                    f"{t.prize_gold}g prize"
                    + (f" + {t.prize_faction_amount} {t.prize_faction} rep" if t.prize_faction else "")
                    + "."
                ),
                tags=["milestone", "tournament_won", t.slug],
                dedupe=False,
            )
            winner_entry.status = "winner"

        # Stamp the rest as finished and journal it
        for e in entries[1:]:
            e.status = "finished"
            h = db.get(Hero, e.hero_id)
            if h is None:
                continue
            db.add(
                JournalEntry(
                    hero_id=h.id, tick_id=current_tick,
                    kind="milestone",
                    text=f"{t.name} closed. {e.kills} kills. Winner: {winner.name if winner else 'unknown'}.",
                    tags=["milestone", "tournament_finished", t.slug],
                )
            )

        t.status = "closed"
        closed.append(t.slug)
        log.info(
            "closed tournament %s · winner=%s · kills=%d · entries=%d",
            t.slug, winner.name if winner else "?", winner_entry.kills, len(entries),
        )
    return closed
