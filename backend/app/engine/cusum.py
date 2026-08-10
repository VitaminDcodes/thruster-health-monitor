import logging
from typing import Tuple

logger = logging.getLogger(__name__)

class CUSUMDetector:
    """
    Cumulative Sum (CUSUM) Control Chart for drift detection.
    Formulas:
        S_pos[t] = max(0, S_pos[t-1] + residual - k)
        S_neg[t] = max(0, S_neg[t-1] - residual - k)
    Trigger:
        S_pos[t] > h  or  S_neg[t] > h
    """
    def __init__(self, k: float = 0.25, h: float = 4.0):
        self.k = k
        self.h = h
        self.s_pos = 0.0
        self.s_neg = 0.0

    def update(self, residual: float) -> Tuple[float, float, bool]:
        """
        Updates the CUSUM values with a new residual.
        Returns:
            - s_pos (float): Positive CUSUM value
            - s_neg (float): Negative CUSUM value
            - alarm (bool): True if either CUSUM exceeds the threshold h
        """
        self.s_pos = max(0.0, self.s_pos + residual - self.k)
        self.s_neg = max(0.0, self.s_neg - residual - self.k)
        
        alarm = (self.s_pos > self.h) or (self.s_neg > self.h)
        return self.s_pos, self.s_neg, alarm

    def reset(self):
        self.s_pos = 0.0
        self.s_neg = 0.0
