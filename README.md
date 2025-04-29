<p align="center">
  <img src="https://github.com/andrzejf1994/workshift_sensor/blob/main/logo.png?raw=true" />
</p>

# Workshift Sensor

A custom Home Assistant integration for managing and monitoring your team’s work shifts.

**Features:**
- **Sensor: Today** – shows today’s shift number with attributes:
  - `shift_start`: full ISO timestamp when the shift begins
  - `shift_end`: full ISO timestamp when the shift ends
- **Sensor: Tomorrow** – shows tomorrow’s shift number (with optional custom workday sensor override)
- **Binary Sensor: Active** – indicates if a shift is currently active (including overnight overlap)

---

## 📦 Installation

### Via HACS (custom repository)

1. Go to **HACS → Integrations → ⋮ → Custom repositories**.
2. Add your repository URL in a code box:
   ```text
   https://github.com/andrzejf1994/workshift_sensor
   ```
3. Select Integration and click Add.
4. In HACS → Integrations, locate Workshift Sensor and click Install.
5. Restart Home Assistant.

### Manual Installation

1. Clone this repo:
```bash
git clone https://github.com/andrzejf1994/workshift_sensor.git
```
2. Copy custom_components/workshift_sensor into your Home Assistant config directory under custom_components/.
3. Restart Home Assistant.

## ⚙️ Configuration

After restarting, navigate to Settings → Integrations → Add Integration → Workshift Sensor and complete the four configuration steps:

**1. General**
- **Integration Name:** A unique name (used as entry title and unique_id prefix)
- **Workday binary sensor:** e.g. binary_sensor.workday_sensor
- **Workday sensor for tomorrow (optional):** override for tomorrow’s workday detection
  
**2. Shifts**
- **Shift duration** (hours)
- **Shifts per day**
  
**3. Start Times**
- Enter the start time for each shift in HH:MM format (defaults: 06:00, 14:00, 22:00, …)
  
**4. Schedule**
- **Schedule start date** (YYYY-MM-DD)
- **Schedule pattern:** a string of digits (0 = off, 1…n = shift number)

## 📝 License

Distributed under the MIT License. See LICENSE for details.
