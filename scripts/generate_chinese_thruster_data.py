import os
import numpy as np
import pandas as pd

def generate_data():
    dt = 0.1  # 10Hz
    records = []
    current_time = 0.0

    # Helper to add noise
    def add_noise(val, std):
        return val + np.random.normal(0, std)

    # Sweep 1: 1600 PWM (Voltage: 22.1V, Current: 0.8A, Temp: 35-37C)
    # 0 to 10s: Neutral
    for _ in range(100):
        records.append({
            "timestamp": round(current_time, 1),
            "pwm": 1500,
            "voltage": round(add_noise(23.0, 0.05), 2),
            "current": round(max(0.01, add_noise(0.05, 0.01)), 2),
            "esc_temperature": round(add_noise(33.0, 0.1), 1)
        })
        current_time += dt

    # 10 to 310s: 1600 PWM Run
    t_1600 = np.array([0, 15, 75, 90, 150, 165, 300])
    temp_1600 = np.array([33, 35, 35, 36, 36, 37, 37])
    curr_1600 = np.array([0.0, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8])
    for step in range(3000):
        t_elapsed = step * dt
        t_temp = np.interp(t_elapsed, t_1600, temp_1600)
        t_curr = np.interp(t_elapsed, t_1600, curr_1600)
        records.append({
            "timestamp": round(current_time, 1),
            "pwm": 1600,
            "voltage": round(add_noise(22.1, 0.05), 2),
            "current": round(max(0.01, add_noise(t_curr, 0.02)), 2),
            "esc_temperature": round(add_noise(t_temp, 0.15), 1)
        })
        current_time += dt

    # 310 to 340s: Cooling Phase
    for step in range(300):
        t_elapsed = step * dt
        t_temp = np.interp(t_elapsed, [0, 30], [37.0, 34.0])
        records.append({
            "timestamp": round(current_time, 1),
            "pwm": 1500,
            "voltage": round(add_noise(23.0, 0.05), 2),
            "current": round(max(0.01, add_noise(0.05, 0.01)), 2),
            "esc_temperature": round(add_noise(t_temp, 0.1), 1)
        })
        current_time += dt

    # Sweep 2: 1700 PWM (Voltage: 21.9V, Current: 3.2-3.3A, Temp: 34-44C)
    # 340 to 640s: 1700 PWM Run
    t_1700 = np.array([0, 15, 30, 45, 60, 75, 90, 105, 120, 135, 150, 165, 180, 195, 210, 225, 240, 255, 270, 285, 300])
    temp_1700 = np.array([34, 35, 36, 37, 38, 39, 39, 40, 40, 41, 41, 42, 42, 42, 43, 43, 43, 44, 44, 44, 44])
    curr_1700 = np.array([0.0, 3.2, 3.2, 3.2, 3.2, 3.2, 3.2, 3.2, 3.3, 3.3, 3.3, 3.3, 3.3, 3.3, 3.3, 3.3, 3.3, 3.3, 3.3, 3.3, 3.3])
    for step in range(3000):
        t_elapsed = step * dt
        t_temp = np.interp(t_elapsed, t_1700, temp_1700)
        t_curr = np.interp(t_elapsed, t_1700, curr_1700)
        records.append({
            "timestamp": round(current_time, 1),
            "pwm": 1700,
            "voltage": round(add_noise(21.9, 0.05), 2),
            "current": round(max(0.01, add_noise(t_curr, 0.04)), 2),
            "esc_temperature": round(add_noise(t_temp, 0.15), 1)
        })
        current_time += dt

    # 640 to 670s: Cooling Phase
    for step in range(300):
        t_elapsed = step * dt
        t_temp = np.interp(t_elapsed, [0, 30], [44.0, 34.0])
        records.append({
            "timestamp": round(current_time, 1),
            "pwm": 1500,
            "voltage": round(add_noise(23.0, 0.05), 2),
            "current": round(max(0.01, add_noise(0.05, 0.01)), 2),
            "esc_temperature": round(add_noise(t_temp, 0.1), 1)
        })
        current_time += dt

    # Sweep 3: 1800 PWM (Voltage: 21.7V, Current: 8.3-9.7A, Temp: 34-54C)
    # At 4:45s (285s), noise occurs and current jumps to 9.4A, then 9.7A
    # 670 to 970s: 1800 PWM Run
    t_1800 = np.array([0, 15, 30, 45, 60, 75, 90, 105, 120, 135, 150, 165, 180, 195, 210, 225, 240, 255, 270, 285, 300])
    temp_1800 = np.array([34, 34, 36, 39, 40, 41, 42, 44, 45, 45, 46, 47, 48, 49, 49, 50, 51, 52, 52, 53, 54])
    curr_1800 = np.array([0.0, 8.5, 8.5, 8.5, 8.5, 8.5, 8.3, 8.3, 8.3, 8.3, 8.3, 8.3, 8.9, 8.8, 8.8, 8.7, 8.7, 8.7, 8.7, 9.4, 9.7])
    for step in range(3000):
        t_elapsed = step * dt
        t_temp = np.interp(t_elapsed, t_1800, temp_1800)
        t_curr = np.interp(t_elapsed, t_1800, curr_1800)
        records.append({
            "timestamp": round(current_time, 1),
            "pwm": 1800,
            "voltage": round(add_noise(21.7, 0.05), 2),
            "current": round(max(0.01, add_noise(t_curr, 0.06)), 2),
            "esc_temperature": round(add_noise(t_temp, 0.15), 1)
        })
        current_time += dt

    # 970 to 1000s: Cooling Phase
    for step in range(300):
        t_elapsed = step * dt
        t_temp = np.interp(t_elapsed, [0, 30], [54.0, 35.0])
        records.append({
            "timestamp": round(current_time, 1),
            "pwm": 1500,
            "voltage": round(add_noise(23.0, 0.05), 2),
            "current": round(max(0.01, add_noise(0.05, 0.01)), 2),
            "esc_temperature": round(add_noise(t_temp, 0.1), 1)
        })
        current_time += dt

    # Sweep 4: 1900 PWM (Voltage: 21.5V, Current: 15.8-17.0A, Temp: 35-68C)
    # At 4:30s (270s), noise occurs and current jumps to 17.0A, then 16.6A
    # 1000 to 1300s: 1900 PWM Run
    t_1900 = np.array([0, 15, 30, 45, 60, 75, 90, 105, 120, 135, 150, 165, 180, 195, 210, 225, 240, 255, 270, 285, 300])
    temp_1900 = np.array([35, 39, 41, 44, 47, 50, 52, 52, 55, 57, 58, 59, 61, 62, 63, 64, 65, 66, 66, 67, 68])
    curr_1900 = np.array([0.0, 15.8, 15.8, 15.8, 15.8, 15.8, 15.8, 15.8, 15.8, 15.8, 15.8, 15.8, 15.8, 15.8, 15.8, 15.7, 15.7, 15.7, 17.0, 16.6, 16.5])
    for step in range(3000):
        t_elapsed = step * dt
        t_temp = np.interp(t_elapsed, t_1900, temp_1900)
        t_curr = np.interp(t_elapsed, t_1900, curr_1900)
        records.append({
            "timestamp": round(current_time, 1),
            "pwm": 1900,
            "voltage": round(add_noise(21.5, 0.05), 2),
            "current": round(max(0.01, add_noise(t_curr, 0.12)), 2),
            "esc_temperature": round(add_noise(t_temp, 0.2), 1)
        })
        current_time += dt

    # Save to CSV
    df = pd.DataFrame(records)
    output_dir = "data/sample"
    os.makedirs(output_dir, exist_ok=True)
    df.to_csv(os.path.join(output_dir, "chinese_thruster_test.csv"), index=False)
    print(f"Successfully generated {len(df)} samples in data/sample/chinese_thruster_test.csv")

if __name__ == "__main__":
    generate_data()
