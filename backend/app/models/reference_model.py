import os
import pandas as pd
import numpy as np
from scipy.interpolate import RegularGridInterpolator
import logging

logger = logging.getLogger(__name__)

class ReferenceModel:
    def __init__(self, reference_dir: str, pwm_neutral: int = 1500, pwm_deadband: int = 25):
        self.reference_dir = reference_dir
        self.pwm_neutral = pwm_neutral
        self.pwm_deadband = pwm_deadband
        
        self.interpolators = {}
        self.grid_bounds = {}  # Store min/max bounds for each map
        
        self._load_all_maps()
        
    def _load_all_maps(self):
        map_files = {
            "current": "current_map.csv",
            "thrust": "thrust_map.csv",
            "power": "power_map.csv",
            "rpm": "rpm_map.csv",
            "efficiency": "efficiency_map.csv"
        }
        
        for key, filename in map_files.items():
            path = os.path.join(self.reference_dir, filename)
            if not os.path.exists(path):
                logger.warning(f"Reference map file not found: {path}. Map '{key}' will not be available.")
                continue
                
            try:
                # Load CSV
                df = pd.read_csv(path)
                
                # Check required columns
                required_cols = {"pwm", "voltage", "value"}
                if not required_cols.issubset(df.columns):
                    logger.error(f"Invalid columns in {filename}. Expected: pwm, voltage, value")
                    continue
                
                # Extract unique sorted coordinates
                pwms = sorted(df["pwm"].unique())
                voltages = sorted(df["voltage"].unique())
                
                # Pivot table to construct 2D values grid (rows: pwm, cols: voltage)
                pivoted = df.pivot(index="pwm", columns="voltage", values="value")
                values_grid = pivoted.to_numpy()
                
                # Create RegularGridInterpolator
                # Method can be 'linear' or 'halton', linear is standard and robust
                interpolator = RegularGridInterpolator(
                    (pwms, voltages),
                    values_grid,
                    bounds_error=False,
                    fill_value=None  # will be handled manually via clipping
                )
                
                self.interpolators[key] = interpolator
                self.grid_bounds[key] = {
                    "pwm_min": min(pwms),
                    "pwm_max": max(pwms),
                    "voltage_min": min(voltages),
                    "voltage_max": max(voltages)
                }
                logger.info(f"Successfully loaded and initialized reference map '{key}' from {filename}")
                
            except Exception as e:
                logger.error(f"Error loading reference map '{key}' from {path}: {str(e)}")

    def _interpolate(self, key: str, pwm: float, voltage: float) -> float:
        if key not in self.interpolators:
            # Fallback default values if map doesn't exist
            if key == "current":
                return 0.05
            return 0.0
            
        # Check deadband for physical quantities that should be zero at neutral
        if abs(pwm - self.pwm_neutral) <= self.pwm_deadband:
            if key == "current":
                return 0.05 # Quiescent current of ESC
            elif key == "power":
                return voltage * 0.05
            else:
                return 0.0
                
        # Clip inputs to the model grid bounds to prevent out-of-bounds extrapolation errors
        bounds = self.grid_bounds[key]
        clipped_pwm = np.clip(pwm, bounds["pwm_min"], bounds["pwm_max"])
        clipped_voltage = np.clip(voltage, bounds["voltage_min"], bounds["voltage_max"])
        
        # Interpolate
        # RegularGridInterpolator expects point formatted as [pwm, voltage]
        point = np.array([[clipped_pwm, clipped_voltage]])
        result = self.interpolators[key](point)[0]
        
        # RegularGridInterpolator might return NaN if inputs are NaN
        if np.isnan(result):
            return 0.0
            
        return float(result)

    def get_expected_current(self, pwm: float, voltage: float) -> float:
        """Returns the expected ESC/motor supply current in Amps."""
        return self._interpolate("current", pwm, voltage)

    def get_expected_power(self, pwm: float, voltage: float) -> float:
        """Returns the expected electric power in Watts."""
        if "power" in self.interpolators:
            return self._interpolate("power", pwm, voltage)
        # Fallback to calculated power
        return self.get_expected_current(pwm, voltage) * voltage

    def get_expected_thrust(self, pwm: float, voltage: float) -> float:
        """Returns the expected thrust in kgf (kilograms-force)."""
        return self._interpolate("thrust", pwm, voltage)

    def get_expected_rpm(self, pwm: float, voltage: float) -> float:
        """Returns the expected motor RPM."""
        return self._interpolate("rpm", pwm, voltage)

    def get_expected_efficiency(self, pwm: float, voltage: float) -> float:
        """Returns expected efficiency (thrust grams per watt)."""
        return self._interpolate("efficiency", pwm, voltage)
        
    def is_out_of_bounds(self, key: str, pwm: float, voltage: float) -> bool:
        """Returns True if the parameters fall outside the calibrated limits of the reference model."""
        if key not in self.grid_bounds:
            return False
        bounds = self.grid_bounds[key]
        return (pwm < bounds["pwm_min"] or pwm > bounds["pwm_max"] or
                voltage < bounds["voltage_min"] or voltage > bounds["voltage_max"])

    def get_coverage_status(self, pwm: float, voltage: float) -> Tuple[str, float]:
        """
        Determines the reference model coverage for the operating point.
        Returns:
            - status (str): "VALID", "LOW_COVERAGE", or "OUT_OF_RANGE"
            - confidence_multiplier (float): Factor to scale overall health confidence [0.0, 1.0]
        """
        pwm_min, pwm_max = 1100.0, 1900.0
        volt_min, volt_max = 10.0, 20.0
        
        if "current" in self.grid_bounds:
            b = self.grid_bounds["current"]
            pwm_min, pwm_max = b["pwm_min"], b["pwm_max"]
            volt_min, volt_max = b["voltage_min"], b["voltage_max"]
            
        if (pwm < pwm_min or pwm > pwm_max or
            voltage < volt_min or voltage > volt_max):
            return "OUT_OF_RANGE", 0.20
            
        pwm_margin = 50.0
        volt_margin = 0.5
        
        if (pwm < (pwm_min + pwm_margin) or pwm > (pwm_max - pwm_margin) or
            voltage < (volt_min + volt_margin) or voltage > (volt_max - volt_margin)):
            return "LOW_COVERAGE", 0.65
            
        return "VALID", 1.0
