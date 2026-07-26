"""Runnable delta-neutral funding-carry bot (long spot + short perp).

Paper-first and venue-injected: all logic is testable offline against
`PaperVenue`; a real exchange adapter implements the same `Venue` protocol.
Live trading is gated behind an explicit flag — the bot never places real
orders by default.
"""
from .bot import CarryBot, CarryBotConfig
from .venue import PaperVenue, Venue

__all__ = ["CarryBot", "CarryBotConfig", "PaperVenue", "Venue"]
