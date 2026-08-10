import math
import logging
from collections import deque
from typing import Dict, Any, Tuple, Optional
import numpy as np

logger = logging.getLogger(__name__)

class OperatingRegionClassifier:
    @staticmethod
    def get_region(pwm: float, last_pwm: Optional[float], pwm_neutral: int = 1500, deadband: int = 25) -> str:
        """Classifies the operating region of the thruster based on PWM command and transitions."""
        dp = pwm - pwm_neutral
        abs_dp = abs(dp)
        
        # 1. Check for rapid commanded transient
        if last_pwm is not None:
            # If PWM command changed by more than 50us within one tick (500us/s rate of change)
            if abs(pwm - last_pwm) > 50.0:
                return "TRANSITION"
                
        # 2. Normal region classification
        if abs_dp <= deadband:
            return "NEUTRAL"
        elif dp > 0:
            return "FORWARD"
        else:
            return "REVERSE"


class WelfordAccumulator:
    """
    Welford's algorithm for running mean, variance, and standard deviation.
    Allows exact incremental statistical updates.
    """
    def __init__(self, count: int = 0, mean: float = 0.0, m2: float = 0.0, 
                 min_val: float = float('inf'), max_val: float = float('-inf')):
        self.count = count
        self.mean = mean
        self.m2 = m2
        self.min_val = min_val if count > 0 else float('inf')
        self.max_val = max_val if count > 0 else float('-inf')

    def update(self, val: float):
        self.count += 1
        delta = val - self.mean
        self.mean += delta / self.count
        delta2 = val - self.mean
        self.m2 += delta * delta2
        
        if val < self.min_val:
            self.min_val = val
        if val > self.max_val:
            self.max_val = val

    @property
    def variance(self) -> float:
        if self.count < 2:
            return 0.0
        return self.m2 / (self.count - 1)

    @property
    def std_dev(self) -> float:
        return math.sqrt(self.variance)


class BaselineStatisticsManager:
    def __init__(self, min_samples: int = 150, default_std_floor: float = 0.1):
        self.min_samples = min_samples
        self.default_std_floor = default_std_floor
        # region -> WelfordAccumulator
        self.accumulators: Dict[str, WelfordAccumulator] = {
            "NEUTRAL": WelfordAccumulator(),
            "FORWARD": WelfordAccumulator(),
            "REVERSE": WelfordAccumulator(),
            "TRANSITION": WelfordAccumulator()
        }
        # Fixed size rolling queues for percentiles and median calculations
        self.windows: Dict[str, deque] = {
            "NEUTRAL": deque(maxlen=1000),
            "FORWARD": deque(maxlen=1000),
            "REVERSE": deque(maxlen=1000),
            "TRANSITION": deque(maxlen=1000)
        }

    def load_from_db_records(self, records: list):
        """Load baseline stats from DB records."""
        for rec in records:
            region = rec["operating_region"]
            if region in self.accumulators:
                self.accumulators[region] = WelfordAccumulator(
                    count=rec["sample_count"],
                    mean=rec["mean_residual"],
                    m2=rec["m2_residual"],
                    min_val=rec["min_residual"],
                    max_val=rec["max_residual"]
                )
                # Seed the window with the mean value to avoid N/A on reload
                if rec["sample_count"] > 0:
                    for _ in range(min(50, rec["sample_count"])):
                        self.windows[region].append(rec["mean_residual"])
                        
        logger.info(f"Loaded baseline statistics for regions: {[r for r, acc in self.accumulators.items() if acc.count > 0]}")

    def update_baseline(self, region: str, residual: float):
        if region in self.accumulators:
            self.accumulators[region].update(residual)
            if region in self.windows:
                self.windows[region].append(residual)

    def get_baseline_state(self, region: str) -> str:
        """Classifies baseline establishing state machine (Section 14)."""
        if region not in self.accumulators:
            return "NOT ESTABLISHED"
        count = self.accumulators[region].count
        if count == 0:
            return "NOT ESTABLISHED"
        elif count < self.min_samples:
            return "INSUFFICIENT"
        elif count < 500:
            return "PRELIMINARY"
        else:
            return "VALIDATED"

    def get_z_score(self, region: str, residual: float) -> Tuple[Optional[float], str]:
        """
        Calculates the Z-score for a residual.
        Returns:
            - z_score (float or None): Z-score if baseline is established
            - status (str): Baseline status state (Section 14)
        """
        status = self.get_baseline_state(region)
        if status in ("NOT ESTABLISHED", "INSUFFICIENT"):
            # Return N/A equivalent in Python (None)
            return None, status
            
        acc = self.accumulators[region]
        std = acc.std_dev
        if std < self.default_std_floor:
            std = self.default_std_floor
            
        z = (residual - acc.mean) / std
        return z, status

    def get_stats_summary(self, region: str) -> Dict[str, Any]:
        if region not in self.accumulators:
            return {}
        acc = self.accumulators[region]
        summary = {
            "count": acc.count,
            "mean": acc.mean,
            "std_dev": acc.std_dev,
            "variance": acc.variance,
            "min": acc.min_val if acc.count > 0 else 0.0,
            "max": acc.max_val if acc.count > 0 else 0.0,
            "baseline_state": self.get_baseline_state(region),
            # Default fallback for percentiles
            "median": 0.0,
            "mad": 0.0,
            "p5": 0.0,
            "p25": 0.0,
            "p75": 0.0,
            "p95": 0.0
        }
        
        # Calculate dynamic percentiles if rolling window has data
        win = self.windows.get(region)
        if win and len(win) > 0:
            win_arr = np.array(win)
            median = float(np.median(win_arr))
            summary["median"] = median
            summary["mad"] = float(np.median(np.abs(win_arr - median)))
            summary["p5"] = float(np.percentile(win_arr, 5))
            summary["p25"] = float(np.percentile(win_arr, 25))
            summary["p75"] = float(np.percentile(win_arr, 75))
            summary["p95"] = float(np.percentile(win_arr, 95))
            
        return summary
