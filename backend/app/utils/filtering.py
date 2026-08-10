import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class FirstOrderLowPassFilter:
    """
    First-order digital low-pass filter (Exponential Moving Average)
    Formula: y[k] = alpha * x[k] + (1 - alpha) * y[k-1]
    Where:
        alpha = dt / (tau + dt)
        dt = sample time interval (s)
        tau = filter time constant (s)
    """
    def __init__(self, tau: float = 0.5, dt: float = 0.1, initial_value: float = None):
        self.tau = tau
        self.dt = dt
        self.alpha = dt / (tau + dt) if (tau + dt) > 0 else 1.0
        self.y_prev = initial_value
        
    def filter(self, x: float) -> float:
        if self.y_prev is None:
            self.y_prev = x
            return x
            
        y = self.alpha * x + (1.0 - self.alpha) * self.y_prev
        self.y_prev = y
        return y
        
    def set_time_constant(self, tau: float):
        self.tau = tau
        self.alpha = self.dt / (tau + self.dt) if (tau + self.dt) > 0 else 1.0

    def reset(self, initial_value: float = None):
        self.y_prev = initial_value
