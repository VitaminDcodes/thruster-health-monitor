import os
import csv
import math

def generate_reference_maps(target_dir):
    os.makedirs(target_dir, exist_ok=True)
    
    voltages = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0]
    # PWM from 1100 to 1900 in 25 us steps
    pwms = list(range(1100, 1901, 25))
    
    # Headers
    headers = ["pwm", "voltage", "value"]
    
    currents = []
    thrusts = []
    powers = []
    rpms = []
    efficiencies = []
    
    for v in voltages:
        for p in pwms:
            # Shift relative to neutral (1500)
            dp = p - 1500
            
            # Deadband check (1475 to 1525)
            if abs(dp) <= 25:
                curr = 0.05  # quiescent current of ESC
                thrust = 0.0
                power = v * curr
                rpm = 0.0
                eff = 0.0
            else:
                # Normalized throttle [0, 1]
                u = (abs(dp) - 25) / (400 - 25)
                direction = 1.0 if dp > 0 else -1.0
                
                # Base current at 16V
                # forward max ~ 24A, reverse max ~ 22A
                max_curr_16 = 24.0 if direction > 0 else 22.0
                
                # Scale max current based on voltage
                # 12V -> 17A (fwd), 16V -> 24A (fwd), 20V -> 32A (fwd)
                if v <= 16.0:
                    max_curr = 17.0 + (v - 12.0) * (max_curr_16 - 17.0) / 4.0
                else:
                    max_curr = max_curr_16 + (v - 16.0) * (32.0 - max_curr_16) / 4.0
                
                # If reverse, scale slightly down
                if direction < 0:
                    max_curr *= 0.92
                
                # Nonlinear relationship for current: I = I_max * (0.3 * u + 0.7 * u^2)
                curr = max_curr * (0.3 * u + 0.7 * (u ** 2))
                
                # Max thrust: 12V -> 3.71 kgf, 16V -> 5.25 kgf, 20V -> 6.70 kgf
                if v <= 16.0:
                    max_thrust = 3.71 + (v - 12.0) * (5.25 - 3.71) / 4.0
                else:
                    max_thrust = 5.25 + (v - 16.0) * (6.70 - 5.25) / 4.0
                
                if direction < 0:
                    max_thrust *= 0.85 # Less efficient in reverse
                
                thrust = max_thrust * (0.2 * u + 0.8 * (u ** 2.2)) * direction
                power = v * curr
                
                # Max RPM: ~3000 RPM at 16V
                max_rpm = 1800 + (v - 10.0) * 150.0
                rpm = max_rpm * (0.4 * u + 0.6 * u) * direction
                
                # Efficiency: thrust (N) * velocity / electrical power
                # For static/bollard, efficiency is often calculated as thrust (gf) / W
                thrust_gf = abs(thrust) * 1000.0
                eff = thrust_gf / max(0.1, power)
                
            currents.append((p, v, round(curr, 3)))
            thrusts.append((p, v, round(thrust, 3)))
            powers.append((p, v, round(power, 3)))
            rpms.append((p, v, round(rpm, 1)))
            efficiencies.append((p, v, round(eff, 3)))
            
    # Helper to write maps
    def write_map(filename, data):
        path = os.path.join(target_dir, filename)
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(data)
        print(f"Wrote reference map: {path}")
        
    write_map("current_map.csv", currents)
    write_map("thrust_map.csv", thrusts)
    write_map("power_map.csv", powers)
    write_map("rpm_map.csv", rpms)
    write_map("efficiency_map.csv", efficiencies)

def generate_sample_telemetry(target_path):
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    
    # Headers
    headers = ["timestamp", "pwm", "voltage", "current", "esc_temperature"]
    data = []
    
    # Start time
    t_start = 1718000000.0 # Arbitrary epoch
    
    # 200 seconds of telemetry at 10 Hz = 2000 samples
    samples = 2000
    
    # Initial state
    voltage = 16.0
    temp = 22.0
    
    for i in range(samples):
        t = t_start + i * 0.1
        
        # Scenario segments
        sec = i * 0.1
        
        # 1. Startup (0-10s): Neutral
        if sec < 10.0:
            pwm = 1500
        # 2. Low forward (10-30s): Step to 1580
        elif sec < 30.0:
            pwm = 1580
        # 3. Stop (30-40s): Step to 1500
        elif sec < 40.0:
            pwm = 1500
        # 4. Mid reverse (40-60s): Step to 1350
        elif sec < 60.0:
            pwm = 1350
        # 5. Stop (60-70s): Step to 1500
        elif sec < 70.0:
            pwm = 1500
        # 6. High forward (70-100s): Step to 1750
        elif sec < 100.0:
            pwm = 1750
        # 7. Slow ramp down to mid (100-110s)
        elif sec < 110.0:
            pwm = int(1750 - (sec - 100.0) * 10) # 1750 -> 1650
        # 8. Anomaly Phase 1: Mild friction (110-140s) at 1650 pwm
        elif sec < 140.0:
            pwm = 1650
        # 9. Stop & cooldown (140-160s): Neutral
        elif sec < 160.0:
            pwm = 1500
        # 10. Anomaly Phase 2: Severe binding/friction (160-190s) at 1800 pwm
        elif sec < 190.0:
            pwm = 1800
        # 11. Cooldown & end (190-200s): Neutral
        else:
            pwm = 1500
            
        # Physics simulation for sample data
        dp = pwm - 1500
        if abs(dp) <= 25:
            base_curr = 0.05
        else:
            u = (abs(dp) - 25) / (400 - 25)
            # Max current fwd is 24A at 16V
            max_curr = 24.0 if dp > 0 else 20.2
            base_curr = max_curr * (0.3 * u + 0.7 * (u ** 2))
            
        # Add voltage fluctuation (slight sag under load)
        voltage = 16.2 - (base_curr * 0.02) + math.sin(sec * 0.5) * 0.05
        
        # Inject anomalies
        # Anomaly 1: Mild friction (+25% current draw)
        if 110.0 <= sec < 140.0:
            current_val = base_curr * 1.25
        # Anomaly 2: Severe friction (+50% current draw + higher temperature)
        elif 160.0 <= sec < 190.0:
            current_val = base_curr * 1.55
        else:
            current_val = base_curr
            
        # Add random noise to current
        current_val += (math.sin(sec * 100) * 0.04) + 0.02
        if current_val < 0:
            current_val = 0.0
            
        # ESC Temperature model (I^2 heating + dissipation)
        # Power dissipation = I^2 * R_esc
        heat_power = (current_val ** 2) * 0.025
        # Ambient temp = 20.0C
        # Rate of temp change = heat_power * coupling - (temp - ambient) * dissipation
        temp_rate = (heat_power * 0.06) - (temp - 20.0) * 0.015
        
        # Inject thermal anomaly: extra heating during severe friction phase
        if 160.0 <= sec < 190.0:
            temp_rate += 0.2 # Extra internal friction heating
            
        temp += temp_rate * 0.1 # delta_t = 0.1s
        
        # Add sensor noise to temp
        temp_val = temp + (math.sin(sec * 50) * 0.05)
        
        # Format values
        row = [
            f"{sec:.1f}", # Time in seconds from start
            pwm,
            f"{voltage:.2f}",
            f"{current_val:.2f}",
            f"{temp_val:.1f}"
        ]
        data.append(row)
        
    with open(target_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(data)
    print(f"Wrote sample telemetry log: {target_path}")

if __name__ == "__main__":
    ref_dir = "c:/Users/DIVYANSH ARZARE/Downloads/thruster-health-monitor-main/thruster-health-monitor-main/data/reference/t200"
    sample_path = "c:/Users/DIVYANSH ARZARE/Downloads/thruster-health-monitor-main/thruster-health-monitor-main/data/sample/sample_telemetry.csv"
    
    generate_reference_maps(ref_dir)
    generate_sample_telemetry(sample_path)
