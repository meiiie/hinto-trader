"""
Regime Detector - HMM-based Market Regime Detection

Infrastructure layer implementation of Hidden Markov Model
for classifying market regimes.

Author: Backend Engineer AI
Based on spec from: Quant Specialist AI
Version: 1.0
"""

import numpy as np
import pandas as pd
import logging
from typing import List, Optional

from src.domain.entities.candle import Candle
from src.domain.value_objects.regime_result import RegimeResult, RegimeType
from src.domain.interfaces.i_regime_detector import IRegimeDetector


class RegimeDetector(IRegimeDetector):
    """
    Hidden Markov Model-based market regime detector.

    Classifies market into 3 states:
    - TRENDING_LOW_VOL: Best conditions for trend pullback
    - TRENDING_HIGH_VOL: Tradeable but with caution
    - RANGING: Do not trade

    Uses 4 features:
    1. Log returns (z-scored)
    2. Realized volatility
    3. ADX (trend strength, normalized)
    4. Volume ratio

    Usage:
        detector = RegimeDetector()
        detector.fit(historical_candles)  # Train on history
        result = detector.detect_regime(recent_candles)  # Real-time detection
    """

    # Minimum candles for reliable detection
    MIN_CANDLES = 50

    # Pre-trained state mappings (based on SOTA research)
    # These will be refined after fitting
    STATE_MAPPING = {
        0: RegimeType.TRENDING_LOW_VOL,
        1: RegimeType.TRENDING_HIGH_VOL,
        2: RegimeType.RANGING
    }

    def __init__(
        self,
        n_states: int = 3,
        feature_window: int = 20,
        adx_trending_threshold: float = 25.0,
        vol_percentile_threshold: float = 50.0
    ):
        """
        Initialize regime detector.

        Args:
            n_states: Number of hidden states (default 3)
            feature_window: Rolling window for feature calculation
            adx_trending_threshold: ADX threshold to consider trending
            vol_percentile_threshold: Volatility percentile for high/low classification
        """
        self.n_states = n_states
        self.feature_window = feature_window
        self.adx_threshold = adx_trending_threshold
        self.vol_threshold = vol_percentile_threshold

        self._model = None
        self._is_fitted = False
        self.logger = logging.getLogger(self.__class__.__name__)

        # Cache for historical volatility percentiles
        self._vol_history: List[float] = []

        # Try to import hmmlearn
        try:
            from hmmlearn import hmm
            self._model = hmm.GaussianHMM(
                n_components=n_states,
                covariance_type="full",
                n_iter=100,
                random_state=42
            )
            self._hmm_available = True
            self.logger.info("HMM module loaded successfully")
        except ImportError:
            self._hmm_available = False
            self.logger.warning(
                "hmmlearn not installed. Using rule-based fallback. "
                "Install with: pip install hmmlearn"
            )

    @property
    def is_fitted(self) -> bool:
        """Check if detector has been trained."""
        return self._is_fitted

    def fit(self, candles: List[Candle]) -> "RegimeDetector":
        """
        Train HMM on historical data.

        Args:
            candles: Historical candles (min 200 recommended)

        Returns:
            self (for chaining)
        """
        if len(candles) < 100:
            raise ValueError(f"Need at least 100 candles for training, got {len(candles)}")

        if not self._hmm_available:
            self.logger.warning("HMM not available, using rule-based fallback")
            self._is_fitted = True
            return self

        features = self._extract_features(candles)

        if features is None or len(features) < 50:
            self.logger.error("Insufficient features extracted for training")
            return self

        try:
            self._model.fit(features)
            self._is_fitted = True

            # Calibrate state mapping based on training data
            self._calibrate_state_mapping(candles, features)

            self.logger.info(f"✅ RegimeDetector fitted on {len(candles)} candles")
        except Exception as e:
            self.logger.error(f"Error fitting HMM: {e}")
            self._is_fitted = False

        return self

    def detect_regime(self, candles: List[Candle]) -> Optional[RegimeResult]:
        """
        Detect current market regime.

        Args:
            candles: Recent candles (minimum 50)

        Returns:
            RegimeResult with classification and probabilities
        """
        if len(candles) < self.MIN_CANDLES:
            self.logger.warning(f"Insufficient candles: {len(candles)} < {self.MIN_CANDLES}")
            return None

        # If not fitted or HMM unavailable, use rule-based fallback
        if not self._is_fitted or not self._hmm_available:
            return self._rule_based_detection(candles)

        # Extract features
        features = self._extract_features(candles)

        if features is None or len(features) == 0:
            return self._rule_based_detection(candles)

        try:
            # Get state probabilities for latest observation
            state_probs = self._model.predict_proba(features)[-1]

            # Most likely state
            current_state = np.argmax(state_probs)
            regime = self.STATE_MAPPING.get(current_state, RegimeType.RANGING)

            # Build probability dict
            probabilities = {
                self.STATE_MAPPING[i]: float(state_probs[i])
                for i in range(self.n_states)
            }

            # Feature values for debugging
            latest_features = features[-1]
            feature_dict = {
                "returns_zscore": float(latest_features[0]),
                "volatility": float(latest_features[1]),
                "adx_normalized": float(latest_features[2]),
                "volume_ratio": float(latest_features[3])
            }

            # Trading decision
            should_trade = regime in [RegimeType.TRENDING_LOW_VOL, RegimeType.TRENDING_HIGH_VOL]
            confidence = float(state_probs[current_state])

            result = RegimeResult(
                regime=regime,
                probabilities=probabilities,
                confidence=confidence,
                features=feature_dict,
                should_trade=should_trade
            )

            self.logger.info(f"🎯 Regime detected: {result}")
            return result

        except Exception as e:
            self.logger.error(f"Error in HMM prediction: {e}")
            return self._rule_based_detection(candles)

    def _extract_features(self, candles: List[Candle]) -> Optional[np.ndarray]:
        """Extract feature matrix from candles."""
        try:
            closes = np.array([c.close for c in candles], dtype=float)
            highs = np.array([c.high for c in candles], dtype=float)
            lows = np.array([c.low for c in candles], dtype=float)
            volumes = np.array([c.volume for c in candles], dtype=float)

            # Feature 1: Log returns (z-scored)
            returns = np.diff(np.log(closes))
            returns = np.append(0, returns)  # Pad first element

            returns_series = pd.Series(returns)
            returns_mean = returns_series.rolling(self.feature_window).mean()
            returns_std = returns_series.rolling(self.feature_window).std()
            returns_zscore = (returns - returns_mean) / returns_std.replace(0, 1)

            # Feature 2: Realized volatility (annualized)
            volatility = returns_series.rolling(self.feature_window).std() * np.sqrt(252 * 24 * 4)

            # Feature 3: ADX (trend strength, normalized)
            adx = self._calculate_adx_series(highs, lows, closes, period=14)
            adx_normalized = adx / 100.0

            # Feature 4: Volume ratio (clipped)
            volume_series = pd.Series(volumes)
            volume_sma = volume_series.rolling(self.feature_window).mean()
            volume_ratio = np.clip(volumes / volume_sma.replace(0, 1), 0.5, 3.0)

            # Stack features (drop NaN rows)
            features_df = pd.DataFrame({
                'returns': returns_zscore,
                'volatility': volatility,
                'adx': adx_normalized,
                'volume': volume_ratio
            }).dropna()

            if len(features_df) < 20:
                return None

            return features_df.values

        except Exception as e:
            self.logger.error(f"Error extracting features: {e}")
            return None

    def _calculate_adx_series(
        self,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        period: int = 14
    ) -> np.ndarray:
        """Simplified ADX calculation."""
        # True Range
        tr1 = highs - lows
        tr2 = np.abs(highs - np.roll(closes, 1))
        tr3 = np.abs(lows - np.roll(closes, 1))
        tr = np.maximum(np.maximum(tr1, tr2), tr3)
        tr[0] = tr1[0]

        # Directional Movement
        up_move = highs - np.roll(highs, 1)
        down_move = np.roll(lows, 1) - lows

        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

        # Smoothed averages
        atr = pd.Series(tr).ewm(span=period).mean()
        plus_di = 100 * pd.Series(plus_dm).ewm(span=period).mean() / atr
        minus_di = 100 * pd.Series(minus_dm).ewm(span=period).mean() / atr

        # ADX
        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, 1)
        adx = dx.ewm(span=period).mean()

        return adx.fillna(0).values

    def _rule_based_detection(self, candles: List[Candle]) -> RegimeResult:
        """
        Fallback rule-based detection when HMM not fitted.
        Uses ADX and volatility thresholds.
        """
        features = self._extract_features(candles)

        if features is None or len(features) == 0:
            # Default to ranging if we can't calculate features
            return RegimeResult(
                regime=RegimeType.RANGING,
                probabilities={
                    RegimeType.TRENDING_LOW_VOL: 0.1,
                    RegimeType.TRENDING_HIGH_VOL: 0.1,
                    RegimeType.RANGING: 0.8
                },
                confidence=0.5,
                features={},
                should_trade=False
            )

        latest = features[-1]

        adx_value = latest[2] * 100  # De-normalize
        volatility = latest[1]

        # Update volatility history for percentile
        self._vol_history.append(volatility)
        if len(self._vol_history) > 500:
            self._vol_history = self._vol_history[-500:]

        vol_percentile = (
            np.percentile(self._vol_history, self.vol_threshold)
            if len(self._vol_history) > 20
            else volatility
        )

        # Classification rules
        if adx_value >= self.adx_threshold:
            if volatility < vol_percentile:
                regime = RegimeType.TRENDING_LOW_VOL
                confidence = 0.8
            else:
                regime = RegimeType.TRENDING_HIGH_VOL
                confidence = 0.7
        else:
            regime = RegimeType.RANGING
            confidence = 0.75

        probabilities = {
            RegimeType.TRENDING_LOW_VOL: 0.33,
            RegimeType.TRENDING_HIGH_VOL: 0.33,
            RegimeType.RANGING: 0.34
        }
        probabilities[regime] = confidence

        feature_dict = {
            "returns_zscore": float(latest[0]),
            "volatility": float(volatility),
            "adx_normalized": float(latest[2]),
            "volume_ratio": float(latest[3])
        }

        should_trade = regime != RegimeType.RANGING

        result = RegimeResult(
            regime=regime,
            probabilities=probabilities,
            confidence=confidence,
            features=feature_dict,
            should_trade=should_trade
        )

        self.logger.info(f"🎯 Rule-based regime: {result}")
        return result

    def _calibrate_state_mapping(self, candles: List[Candle], features: np.ndarray) -> None:
        """
        After fitting, determine which HMM state corresponds to which regime.
        Based on mean ADX and volatility of each state.
        """
        try:
            states = self._model.predict(features)

            state_stats = {}
            for state in range(self.n_states):
                mask = states == state
                if mask.any():
                    state_stats[state] = {
                        'adx_mean': features[mask, 2].mean() * 100,
                        'vol_mean': features[mask, 1].mean()
                    }

            # Sort states: highest ADX + lowest vol = best trending
            # Lowest ADX = ranging
            sorted_states = sorted(
                state_stats.keys(),
                key=lambda s: (state_stats[s]['adx_mean'], -state_stats[s]['vol_mean']),
                reverse=True
            )

            if len(sorted_states) >= 3:
                self.STATE_MAPPING = {
                    sorted_states[0]: RegimeType.TRENDING_LOW_VOL,
                    sorted_states[1]: RegimeType.TRENDING_HIGH_VOL,
                    sorted_states[2]: RegimeType.RANGING
                }

            self.logger.info(f"State mapping calibrated: {self.STATE_MAPPING}")

        except Exception as e:
            self.logger.error(f"Error calibrating state mapping: {e}")

    def __repr__(self) -> str:
        status = "fitted" if self._is_fitted else "not fitted"
        hmm_status = "HMM" if self._hmm_available else "rule-based"
        return f"RegimeDetector(n_states={self.n_states}, {status}, {hmm_status})"
