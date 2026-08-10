import logging
from typing import Optional

logger = logging.getLogger(__name__)

class EWMATracker:
    """
    Exponentially Weighted Moving Average (EWMA) tracker.
    Formula: z_t = lambda * x_t + (1 - lambda) * z_{t-1}
    Purpose: Smooths residuals and highlights persistent shifts.
    """
    def __init__(self, lambda_factor: float = 0.15, initial_value: float = 0.0):
        self.lambda_factor = lambda_factor
        self.z = initial_value
        self.is_initialized = False

    def update(self, val: float) -> float:
        if not self.is_initialized:
            self.z = val
            self.is_initialized = True
            return self.z
            
        self.z = self.lambda_factor * val + (1.0 - self.lambda_factor) * self.z
        return self.z

    def reset(self, initial_value: float = 0.0):
        self.z = initial_value
        self.is_initialized = False
