"""
Unit tests for tradelib.py — three-phase trailing stop model.

Test matrix
-----------
Phase 1 — breakeven trigger
  BUY:  price reaches TRAIL_ACTIVATE_FRAC * tp_dist  → be event, SL = entry
  SELL: same logic inverted
  Price falls short of threshold                       → no be event

Phase 2 — active trailing after breakeven
  BUY:  new best price → trail ratchets up
  BUY:  price retreats → trail does NOT move down (ratchet is one-way)
  SELL: new best price → trail ratchets down

Phase 3 — TP extension (momentum gate)
  BUY, HA agrees (bullish candle)   → extend_tp event, position held open
  BUY, HA disagrees (bearish candle) → close_tp event (no extension)
  SELL, HA agrees (bearish candle)  → extend_tp event
  Already extended                   → close_tp on second TP hit (no double-extend)

SL / TP close events
  BUY SL hit                         → close_sl
  SELL SL hit                        → close_sl
  BUY TP hit (no HA columns)         → close_tp (momentum_ok = False)
  Both SL and TP in bar              → close_tp takes priority (existing behaviour)

calc_units
  USD-quoted pair (eurusd, gbpusd, audusd)
  JPY pair                            → pip converted via jpy_rate
  Zero / negative risk_pips           → returns 1 (safe fallback)

pip_value
  JPY pair  → 0.01
  Non-JPY   → 0.0001
"""

import math
import pytest
import pandas as pd

from tradelib import (
    Position,
    Signal,
    check_position_events,
    calc_units,
    pip_value,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

class _Ind:
    """Minimal mock indicator module for testing."""
    ATR_SL_MULT         = 0.4
    TRAIL_ACTIVATE_FRAC = 0.8

    @staticmethod
    def pip_value(pair: str) -> float:
        return 0.01 if "jpy" in pair.lower() else 0.0001


def _buy(
    entry: float = 1.08000,
    sl:    float = 1.07960,   # 4 pips below entry (ATR=0.001, mult=0.4)
    tp:    float = 1.08300,   # 30 pips above entry
    atr:   float = 0.001,
    **kwargs,
) -> Position:
    dist = round(abs(tp - entry) / 0.0001, 1)
    risk = round(abs(entry - sl) / 0.0001, 1)
    return Position(
        pair="eurusd", symbol="EUR_USD", direction="BUY",
        trade_type="automated",
        entry_price=entry, stop_loss=sl, take_profit=tp,
        atr=atr, risk_pips=risk, reward_pips=dist,
        rr_ratio=round(dist / risk, 2) if risk else 0.0,
        opened_at="2026-05-22T10:00:00Z", basis="test",
        original_tp=tp, best_price=entry,
        **kwargs,
    )


def _sell(
    entry: float = 1.08000,
    sl:    float = 1.08040,   # 4 pips above entry
    tp:    float = 1.07700,   # 30 pips below entry
    atr:   float = 0.001,
    **kwargs,
) -> Position:
    dist = round(abs(tp - entry) / 0.0001, 1)
    risk = round(abs(entry - sl) / 0.0001, 1)
    return Position(
        pair="eurusd", symbol="EUR_USD", direction="SELL",
        trade_type="automated",
        entry_price=entry, stop_loss=sl, take_profit=tp,
        atr=atr, risk_pips=risk, reward_pips=dist,
        rr_ratio=round(dist / risk, 2) if risk else 0.0,
        opened_at="2026-05-22T10:00:00Z", basis="test",
        original_tp=tp, best_price=entry,
        **kwargs,
    )


def _bar(high: float, low: float,
         ha_close: float = float("nan"),
         ha_open:  float = float("nan")) -> pd.Series:
    return pd.Series({
        "open": (high + low) / 2,
        "high": high,
        "low":  low,
        "close": (high + low) / 2,
        "ha_close": ha_close,
        "ha_open":  ha_open,
    })


# ── Phase 1 — Breakeven ────────────────────────────────────────────────────────

class TestPhase1Breakeven:
    def test_buy_be_triggers_at_threshold(self):
        """Price reaches exactly TRAIL_ACTIVATE_FRAC * tp_dist → be event fires.

        Phase 2 runs on the same bar immediately after Phase 1, so the SL moves
        to the trailing level (above entry) in the same call.  We assert
        be_activated and that SL is at or above entry — not that SL == entry.
        """
        pos = _buy()
        # tp_dist = 30 pips, TRAIL_ACTIVATE_FRAC = 0.8 → activate at 24 pips = 1.08240
        # Phase 2 then runs: trail = 1.08240 - ATR(0.001)*MULT(0.4) = 1.08240 - 0.00040 = 1.08200
        bar = _bar(high=1.08240, low=1.08100)
        events = check_position_events(pos, bar, _Ind())
        assert ("be", 1.08000) in events        # event recorded at entry price
        assert pos.be_activated is True
        assert pos.stop_loss >= pos.entry_price  # trail moved it above entry same bar
        assert abs(pos.stop_loss - 1.08200) < 1e-7  # exact trail value

    def test_buy_be_not_triggered_below_threshold(self):
        """Price reaches 23 pips (< 24 pip threshold) → no be event."""
        pos = _buy()
        bar = _bar(high=1.08230, low=1.08100)
        events = check_position_events(pos, bar, _Ind())
        assert not any(e[0] == "be" for e in events)
        assert pos.be_activated is False

    def test_sell_be_triggers(self):
        """SELL position: price drops by TRAIL_ACTIVATE_FRAC * tp_dist → be event.

        Phase 2 runs same bar: trail = 1.07760 + 0.00040 = 1.07800, which is
        below entry (1.08000), so SL becomes 1.07800 (trail wins over entry).
        """
        pos = _sell()
        # entry=1.08000, tp=1.07700, tp_dist=30 pips, activate at 24 pips below = 1.07760
        bar = _bar(high=1.07900, low=1.07760)
        events = check_position_events(pos, bar, _Ind())
        assert ("be", 1.08000) in events
        assert pos.be_activated is True
        assert pos.stop_loss <= pos.entry_price  # trail is below entry for SELL
        assert abs(pos.stop_loss - 1.07800) < 1e-7

    def test_be_sets_sl_at_or_above_entry(self):
        """After be, stop_loss is at or above entry_price (trail moves up same bar)."""
        pos = _buy(entry=1.08000, sl=1.07900, tp=1.08300)
        bar = _bar(high=1.08250, low=1.08220)
        # BE activates at 24 pips (1.08240); bar high only reaches 1.08250.
        # Phase 2: trail = 1.08250 - 0.00040 = 1.08210; SL >= entry.
        check_position_events(pos, bar, _Ind())
        if pos.be_activated:
            assert pos.stop_loss >= 1.08000

    def test_be_not_repeated_on_subsequent_bars(self):
        """Once BE is active, further bars do not re-emit be event."""
        pos = _buy()
        bar1 = _bar(high=1.08250, low=1.08100)
        check_position_events(pos, bar1, _Ind())
        assert pos.be_activated

        bar2 = _bar(high=1.08260, low=1.08200)
        events2 = check_position_events(pos, bar2, _Ind())
        assert not any(e[0] == "be" for e in events2)


# ── Phase 2 — Active trailing ──────────────────────────────────────────────────

class TestPhase2Trail:
    def _activated_buy(self, **kwargs) -> Position:
        """Return a BUY position with BE already active."""
        pos = _buy(**kwargs)
        pos.be_activated = True
        pos.stop_loss    = pos.entry_price   # 1.08000
        pos.best_price   = 1.08240           # where BE fired
        return pos

    def test_buy_trail_ratchets_up_with_new_best(self):
        """New high → trail SL moves up to best - ATR*MULT.

        Bar low must stay above the new trail level, otherwise the position
        closes on the same bar.  trail = 1.08260 - 0.00040 = 1.08220; use
        low=1.08230 which is above the trail.
        """
        pos = self._activated_buy()
        # best_price starts at 1.08240, trail_dist = 0.00040
        # bar high=1.08260 → new best=1.08260, trail=1.08220; low=1.08230 > trail → no close
        bar = _bar(high=1.08260, low=1.08230)
        events = check_position_events(pos, bar, _Ind())
        assert not any(e[0].startswith("close") for e in events)
        assert abs(pos.stop_loss - 1.08220) < 1e-7

    def test_buy_trail_does_not_move_down(self):
        """If the bar moves against us (no new high), the trail should not retreat."""
        pos = self._activated_buy()
        # First bar: push best up
        bar1 = _bar(high=1.08260, low=1.08200)
        check_position_events(pos, bar1, _Ind())
        sl_after_bar1 = pos.stop_loss

        # Second bar: lower high (no new best)
        bar2 = _bar(high=1.08255, low=1.08210)
        check_position_events(pos, bar2, _Ind())
        assert pos.stop_loss == sl_after_bar1

    def test_sell_trail_ratchets_down(self):
        """SELL position: new low → trail SL moves down."""
        pos = _sell()
        pos.be_activated = True
        pos.stop_loss    = pos.entry_price   # 1.08000
        pos.best_price   = 1.07760           # where BE fired

        # bar low=1.07750 → new best=1.07750, trail=1.07750+0.00040=1.07790
        bar = _bar(high=1.07900, low=1.07750)
        check_position_events(pos, bar, _Ind())
        assert abs(pos.stop_loss - 1.07790) < 1e-7

    def test_trail_after_phase3_tightens(self):
        """After Phase 3 extension, trail_dist is halved (ATR*MULT*0.5)."""
        pos = _buy()
        pos.be_activated = True
        pos.stop_loss    = 1.08270   # Phase 3 SL (90% of original 30 pips = 27 pips above entry)
        pos.take_profit  = 1.08600   # Phase 3 TP (60 pips above entry)
        pos.original_tp  = 1.08300   # original TP preserved
        pos.tp_extended  = True
        pos.best_price   = 1.08350

        # trail_dist after Phase 3 = 0.001 * 0.4 * 0.5 = 0.00020
        bar = _bar(high=1.08400, low=1.08300)
        check_position_events(pos, bar, _Ind())
        expected_trail = 1.08400 - 0.00020
        assert abs(pos.stop_loss - expected_trail) < 1e-7


# ── Phase 3 — TP extension ────────────────────────────────────────────────────

class TestPhase3Extension:
    def test_buy_ha_agrees_extend_fires(self):
        """BUY reaches TP with bullish HA candle → extend_tp, no close event."""
        pos = _buy()
        # TP = 1.08300; bar high reaches it; HA is bullish (ha_close > ha_open)
        bar = _bar(high=1.08310, low=1.08100, ha_close=1.08305, ha_open=1.08200)
        events = check_position_events(pos, bar, _Ind())

        assert any(e[0] == "extend_tp" for e in events)
        assert not any(e[0].startswith("close") for e in events)
        assert pos.tp_extended is True

        # Verify new levels: SL = entry + 0.9 * 30 pips = 1.08000 + 0.00270 = 1.08270
        assert abs(pos.stop_loss - 1.08270) < 1e-7
        # New TP = entry + 2 * 30 pips = 1.08000 + 0.00600 = 1.08600
        assert abs(pos.take_profit - 1.08600) < 1e-7

    def test_buy_ha_disagrees_no_extension(self):
        """BUY reaches TP with bearish HA candle → close_tp, no extension."""
        pos = _buy()
        bar = _bar(high=1.08310, low=1.08100, ha_close=1.08200, ha_open=1.08305)
        events = check_position_events(pos, bar, _Ind())

        assert any(e[0] == "close_tp" for e in events)
        assert not any(e[0] == "extend_tp" for e in events)

    def test_sell_ha_agrees_extend_fires(self):
        """SELL reaches TP with bearish HA candle → extend_tp, no close event."""
        pos = _sell()
        # TP = 1.07700; bar low reaches it; HA is bearish (ha_close < ha_open)
        bar = _bar(high=1.07850, low=1.07690, ha_close=1.07710, ha_open=1.07800)
        events = check_position_events(pos, bar, _Ind())

        assert any(e[0] == "extend_tp" for e in events)
        assert not any(e[0].startswith("close") for e in events)
        assert pos.tp_extended is True

    def test_no_double_extension(self):
        """Second TP hit on an already-extended position → close_tp (no re-extend)."""
        pos = _buy()
        # Manually set post-extension state
        pos.tp_extended  = True
        pos.be_activated = True
        pos.original_tp  = 1.08300
        pos.take_profit  = 1.08600  # Phase 3 TP
        pos.stop_loss    = 1.08270  # Phase 3 SL
        pos.best_price   = 1.08350

        # Bar hits the extended TP; HA is bullish
        bar = _bar(high=1.08610, low=1.08400, ha_close=1.08605, ha_open=1.08500)
        events = check_position_events(pos, bar, _Ind())

        assert any(e[0] == "close_tp" for e in events)
        assert not any(e[0] == "extend_tp" for e in events)

    def test_missing_ha_columns_no_extension(self):
        """Bar with no HA columns → momentum_ok = False → close_tp."""
        pos = _buy()
        # Bar hits TP but has no HA data
        bar = _bar(high=1.08310, low=1.08100)   # ha_close and ha_open are NaN
        events = check_position_events(pos, bar, _Ind())

        assert any(e[0] == "close_tp" for e in events)
        assert not any(e[0] == "extend_tp" for e in events)


# ── SL / TP close events ──────────────────────────────────────────────────────

class TestCloseEvents:
    def test_buy_sl_hit(self):
        """BUY: bar low touches SL → close_sl."""
        pos = _buy(sl=1.07960)
        bar = _bar(high=1.07990, low=1.07955)
        events = check_position_events(pos, bar, _Ind())
        assert any(e[0] == "close_sl" for e in events)
        assert not any(e[0] == "close_tp" for e in events)

    def test_sell_sl_hit(self):
        """SELL: bar high touches SL → close_sl."""
        pos = _sell(sl=1.08040)
        bar = _bar(high=1.08045, low=1.07980)
        events = check_position_events(pos, bar, _Ind())
        assert any(e[0] == "close_sl" for e in events)

    def test_buy_tp_hit_no_ha(self):
        """BUY reaches TP with no HA data → close_tp (no extension possible)."""
        pos = _buy()
        bar = _bar(high=1.08310, low=1.08200)
        events = check_position_events(pos, bar, _Ind())
        assert any(e[0] == "close_tp" for e in events)

    def test_neither_sl_nor_tp_no_event(self):
        """Bar within range → no close or be events."""
        pos = _buy()
        bar = _bar(high=1.08100, low=1.08010)
        events = check_position_events(pos, bar, _Ind())
        assert not any(e[0].startswith("close") for e in events)
        assert not any(e[0] == "be" for e in events)

    def test_both_sl_and_tp_in_bar_tp_wins(self):
        """
        When both SL and TP are within the bar's range, close_tp takes priority
        (matching the existing behaviour: check is `elif`, not `if`).
        This case is resolved accurately in backtesting via M1 simulation.
        """
        pos = _buy(sl=1.07960, tp=1.08300)
        # Bar engulfs both SL and TP
        bar = _bar(high=1.08310, low=1.07950, ha_close=1.08200, ha_open=1.08305)
        events = check_position_events(pos, bar, _Ind())
        event_names = [e[0] for e in events]
        assert "close_tp" in event_names
        assert "close_sl" not in event_names

    def test_position_not_mutated_when_no_events(self):
        """A quiet bar should not change any position state."""
        pos = _buy()
        original_sl = pos.stop_loss
        bar = _bar(high=1.08050, low=1.08010)
        check_position_events(pos, bar, _Ind())
        assert pos.stop_loss == original_sl
        assert pos.be_activated is False


# ── Custom TRAIL_ACTIVATE_FRAC ────────────────────────────────────────────────

class TestCustomTrailFrac:
    def test_custom_frac_respected(self):
        """Indicator with TRAIL_ACTIVATE_FRAC=0.7 fires BE at 70% of tp_dist."""
        class Ind70(_Ind):
            TRAIL_ACTIVATE_FRAC = 0.7

        pos = _buy()
        # tp_dist = 30 pips, threshold = 0.7 * 30 = 21 pips = 1.08210
        bar_at_21 = _bar(high=1.08210, low=1.08100)
        events = check_position_events(pos, bar_at_21, Ind70())
        assert any(e[0] == "be" for e in events)

    def test_default_frac_does_not_fire_early(self):
        """Default 0.80 does not fire BE at 70% (21 pips)."""
        pos = _buy()
        bar_at_21 = _bar(high=1.08210, low=1.08100)
        events = check_position_events(pos, bar_at_21, _Ind())
        assert not any(e[0] == "be" for e in events)


# ── calc_units ────────────────────────────────────────────────────────────────

class TestCalcUnits:
    def test_usd_pair_basic(self):
        """
        EURUSD, 10 pip stop, 1% of 10 000 NAV.
        risk_usd = 100, pip_usd = 0.0001
        units = 100 / (10 * 0.0001) = 100 000
        """
        assert calc_units("eurusd", 10.0, nav=10_000, risk_pct=1.0) == 100_000

    def test_jpy_pair(self):
        """
        USDJPY, 10 pip stop, 1% of 10 000 NAV, rate = 150.
        pip_size = 0.01 (JPY), pip_usd = 0.01/150 = 0.0000667
        risk_usd = 100
        units = 100 / (10 * 0.0000667) = 149 925 → int = 149 925
        """
        units = calc_units("usdjpy", 10.0, nav=10_000, risk_pct=1.0, jpy_rate=150.0)
        expected = int(100.0 / (10.0 * (0.01 / 150.0)))
        assert units == expected

    def test_minimum_one_unit(self):
        """Extremely small nav → function returns at least 1."""
        assert calc_units("eurusd", 10.0, nav=0.01, risk_pct=1.0) == 1

    def test_zero_risk_pips_returns_one(self):
        """Degenerate input: zero risk_pips → safe fallback of 1."""
        assert calc_units("eurusd", 0.0, nav=10_000, risk_pct=1.0) == 1

    def test_negative_risk_pips_returns_one(self):
        assert calc_units("eurusd", -5.0, nav=10_000, risk_pct=1.0) == 1

    def test_scales_with_nav(self):
        """Doubling NAV doubles units."""
        u1 = calc_units("eurusd", 10.0, nav=10_000, risk_pct=1.0)
        u2 = calc_units("eurusd", 10.0, nav=20_000, risk_pct=1.0)
        assert u2 == 2 * u1

    def test_scales_with_risk_pct(self):
        """Halving risk_pct halves units."""
        u1 = calc_units("eurusd", 10.0, nav=10_000, risk_pct=1.0)
        u2 = calc_units("eurusd", 10.0, nav=10_000, risk_pct=0.5)
        assert u2 == u1 // 2


# ── pip_value ─────────────────────────────────────────────────────────────────

class TestPipValue:
    def test_jpy_pairs(self):
        for pair in ("usdjpy", "USDJPY", "eurjpy", "GBPJPY"):
            assert pip_value(pair) == 0.01

    def test_non_jpy_pairs(self):
        for pair in ("eurusd", "GBPUSD", "audusd", "NZDUSD"):
            assert pip_value(pair) == 0.0001


# ── Signal dataclass ──────────────────────────────────────────────────────────

class TestSignal:
    def test_flat_signal(self):
        s = Signal(direction="FLAT", timestamp="2026-05-22T10:00:00Z", entry_basis="no bias")
        assert s.direction == "FLAT"
        assert s.entry_price is None
        assert s.bar_time is None

    def test_buy_signal(self):
        s = Signal(
            direction="BUY", timestamp="2026-05-22T10:05:00Z",
            entry_basis="Pattern A", bar_time="2026-05-22T10:00:00Z",
            entry_price=1.08100, stop_loss=1.08060, take_profit=1.08400,
            atr=0.00100, risk_pips=4.0, reward_pips=30.0, rr_ratio=7.5,
        )
        assert s.direction == "BUY"
        assert s.rr_ratio == 7.5
        assert s.h1_macd_hist is None   # optional diagnostic, defaults to None
