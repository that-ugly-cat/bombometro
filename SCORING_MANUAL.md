# Bombometro — Scoring System Manual

> **Version**: current codebase (`core.py`)
> **Data source**: [Open-Meteo](https://open-meteo.com/) hourly forecast
> **Audience**: site configurators, advanced users, developers

---

## Table of Contents

1. [Architecture overview](#1-architecture-overview)
2. [Site configuration parameters](#2-site-configuration-parameters)
3. [Hard veto](#3-hard-veto)
4. [Launch score](#4-launch-score)
5. [Upper wind score](#5-upper-wind-score)
6. [Thermal score](#6-thermal-score)
7. [Risk score](#7-risk-score)
8. [Foehn score](#8-foehn-score)
9. [Potential score](#9-potential-score)
10. [Fly score](#10-fly-score)
11. [Foehn–thermal interaction](#11-foehn-thermal-interaction)
12. [Day summary and verdict](#12-day-summary-and-verdict)
13. [Score interpretation guide](#13-score-interpretation-guide)

---

## 1. Architecture overview

Each forecast hour is evaluated independently through a pipeline:

```
hourly forecast row
        │
        ▼
  [hard_veto]  ──── VETO? ──► fly_score = None
        │ no veto
        ▼
  [launch_score]          → l_sc  (0–100)
  [upper_wind_score]      → u_sc  (0–100)
  [thermal_score]         → th_sc (0–100)
  [risk_score]            → r_sc  (0–100)
  [foehn_score]           → f_sc  (0–100)
        │
        ▼
  potential_score = 0.25·l_sc + 0.35·u_sc + 0.40·th_sc
        │
        ▼
  foehn–thermal interaction → f_sc_adj
        │
        ▼
  risk_pen  = f(r_sc)
  foehn_pen = f(f_sc_adj)
        │
        ▼
  fly_score = clamp(potential − risk_pen − foehn_pen, 0, 100)
        │
        ▼
  [day_summary] → verdict, best_window, etc.
```

All scores are in the range **0–100**.
Convention: **higher = better** for all scores *except* `foehn_score` (higher = more foehn influence = worse for flying) and `risk_score` (higher = more risk = worse).

---

## 2. Site configuration parameters

Each site is defined in `sites.json`. Every scoring function that references a site limit reads from a `SiteConfig` dataclass.

| Parameter | Unit | Description |
|---|---|---|
| `launch_dir_center_deg` | ° | Ideal wind-from direction for launch |
| `launch_dir_tolerance_deg` | ° | Half-width of acceptable direction sector |
| `launch_wind_min_kmh` | km/h | Minimum useful wind at launch |
| `launch_wind_max_kmh` | km/h | Hard maximum wind at launch (veto threshold) |
| `gust_max_kmh` | km/h | Hard maximum gust (veto threshold) |
| `wind_925_max_kmh` | km/h | Maximum acceptable wind at 925 hPa (~750 m) |
| `wind_850_max_kmh` | km/h | Maximum acceptable wind at 850 hPa (~1500 m) |
| `wind_800_max_kmh` | km/h | Maximum acceptable wind at 800 hPa (~1950 m) |
| `wind_700_max_kmh` | km/h | High-altitude limit at 700 hPa (~3000 m) |
| `foehn_delta_p_max_hpa` | hPa | North–south pressure differential triggering scoring |
| `foehn_north_lat/lon` | ° | Windward foehn reference station (e.g. Innsbruck) |
| `foehn_south_lat/lon` | ° | Lee-side foehn reference station (e.g. Bolzano) |
| `precip_max_mm` | mm/h | Maximum tolerable precipitation |
| `snow_max_cm` | cm/h | Maximum tolerable snowfall |
| `cloud_low_max_pct` | % | Low-cloud cover triggering visibility veto |
| `cape_max` | J/kg | CAPE reference for storm scoring |

---

## 3. Hard veto

**Function**: `hard_veto(row, site)`
**Output**: `(vetoed: bool, veto_type: str, reasons: list)`

The hard veto is a binary gate evaluated **before** any scoring. A vetoed hour receives `fly_score = None` and is displayed in the UI with the veto colour. Component scores are still computed for vetoed hours (displayed as ghost bars) to show the underlying potential that the veto overrides.

### Veto conditions

| Condition | Veto type | Meteorological rationale |
|---|---|---|
| Wind direction outside `launch_dir_center ± tolerance` | `wind` | Cannot inflate or run on a cross-wind or tail-wind launch |
| `wind_speed_10m > launch_wind_max_kmh` | `wind` | Exceeds safe launch wind — uncontrolled inflation |
| `wind_speed_925hPa > wind_925_max_kmh` | `wind` | Ridge-level flow too strong for safe thermalling |
| `wind_gusts_10m ≥ gust_max_kmh` | `gusts` | Gust envelope exceeds safe handling margin |
| `precipitation > precip_max_mm` | `precipitation` | Rain makes wing fabric and lines unmanageable; reduces lift |
| `snowfall > snow_max_cm` | `precipitation` | Ice contamination; poor visibility |
| `cloud_cover_low ≥ cloud_low_max_pct` | `visibility` | Launch site in cloud; IMC conditions |
| `delta_p_foehn > foehn_delta_p_max_hpa × 1.20` | `foehn` | Severe foehn gradient — extreme rotor and turbulence likely |

The foehn veto is set at **120% of the scoring threshold** to distinguish between "foehn is building" (scoring) and "foehn is dangerous" (hard stop).

---

## 4. Launch score

**Function**: `launch_score(row, site)`
**Weight in potential**: 25%
**Forecast variables**: `wind_speed_10m`, `wind_direction_10m`, `wind_gusts_10m`, `cloud_cover_low`

### What it represents

The launch score evaluates the conditions at the launch pad specifically: whether the wind will allow a safe, controlled inflation and take-off. It does **not** evaluate in-flight conditions.

### Components

#### Direction score (weight 30%)

```
dir_diff        = angular difference between wind_direction_10m and launch_dir_center_deg
direction_score = clamp(100 × (1 − dir_diff / tolerance), 0, 100)
```

- 100 when wind is perfectly on the ideal heading
- 0 when wind is exactly at the tolerance limit
- Linear degradation between

A 90° tolerance site (e.g. Montegrappa, south-facing) accepts winds from SSE to SSW with no penalty, reaching 0 at exactly 90° off.

#### Speed score (weight 30%)

```
if wind_speed ≤ 10 km/h:
    speed_score = 15 + (wind_speed / 10) × 85      # ramps from 15 (calm) to 100 (10 km/h)
else:
    speed_score = 100 × (1 − (wind_speed − 10) / (launch_wind_max − 10))  # linear to 0 at max
```

- A floor of 15 at dead calm acknowledges that zero wind at launch is less than ideal but not dangerous
- Peak score at 10 km/h — enough to assist inflation without being excessive
- Drops linearly to 0 at `launch_wind_max_kmh`

#### Gust score (weight 25%)

```
gust_ok = wind_speed + 5 km/h      # acceptable gust headroom above mean

if gusts ≤ gust_ok:    gust_score = 100
if gusts ≥ gust_max:   gust_score = 0
else:                  gust_score = 100 × (1 − (gusts − gust_ok) / (gust_max − gust_ok))
```

The `+5 km/h` tolerance represents normal atmospheric gust–lull oscillation. Larger differentials indicate instability or mechanical turbulence close to the terrain, which can collapse the wing during the inflation run.

#### Low cloud score (weight 15%)

```
cloud_score = clamp(100 × (1 − cloud_cover_low / cloud_low_max_pct), 0, 100)
```

Low cloud reduces visibility, can place the launch inside cloud, and indicates a damp boundary layer unfavourable to clean inflation.

#### Final formula

```
launch_score = 0.30 × direction + 0.30 × speed + 0.25 × gusts + 0.15 × cloud
```

---

## 5. Upper wind score

**Function**: `upper_wind_score(row, site)`
**Weight in potential**: 35%
**Forecast variables**: `wind_speed_925/850/800/700hPa`, `wind_direction_925/850/800/700hPa`

### What it represents

The upper wind score evaluates the quality of the wind environment **above the launch**, from the ridge level (~750 m, 925 hPa) up to ~3000 m (700 hPa). This is where soaring flight takes place. It penalises both excessive speeds at any level and incoherence in the vertical wind profile.

### Components

#### Operating score — 925/850/800 hPa (before aloft penalty and coherence)

Each level uses a **peaked function**: score rises toward an optimal wind speed, then falls to 0 at the site limit. A floor of 30 prevents calm upper winds from scoring poorly (light upper flow is fine for thermalling).

```
peaked(wind, peak, max_wind, floor=30):
    if wind ≤ peak:  score = floor + (wind / peak) × (100 − floor)
    else:            score = 100 × (1 − (wind − peak) / (max_wind − peak))
    return clamp(score, 0, 100)
```

| Level | Optimal peak | Meteorological meaning |
|---|---|---|
| 925 hPa (~750 m) | 15 km/h | Ridge-level flow; ideal for steady soaring |
| 850 hPa (~1500 m) | 17 km/h | Mid-thermal layer; slightly higher wind accepted |
| 800 hPa (~1950 m) | 18 km/h | Top of typical XC climb; acceptable with more flow |

```
op = 0.40 × s925 + 0.35 × s850 + 0.25 × s800
```

925 hPa gets the highest weight as it is closest to the actual flying environment and most directly felt by the pilot.

#### High-altitude penalty — 700 hPa (up to −30 pts)

```
aloft_start   = wind_700_max × 0.5
aloft_penalty = 0            if w700 ≤ aloft_start
              = 30           if w700 ≥ wind_700_max
              = 30 × (w700 − aloft_start) / (wind_700_max − aloft_start)   otherwise
```

Strong jet-level flow at 700 hPa (~3000 m) limits XC ceiling height and creates dangerous rotor if pilots inadvertently climb into that layer. It starts penalising at 50% of the site limit and reaches a maximum penalty of 30 points.

#### Vertical coherence penalty — speed and direction jumps (up to −35 pts)

```
speed_jumps = [|w850−w925|, |w800−w850|, |w700−w800|]
dir_jumps   = [Δ°(d850,d925), Δ°(d800,d850), Δ°(d700,d800)]

spj(j) = 0 if j ≤ 8 km/h,   1 if j ≥ 20 km/h,   linear between
dj(j)  = 0 if j ≤ 20°,      1 if j ≥ 60°,        linear between

coh_pen = 35 × (0.6 × mean(spj) + 0.4 × mean(dj))
```

A coherent vertical profile (similar speeds and directions at all levels) indicates organised, laminar flow. Large jumps in speed or direction between adjacent pressure levels are proxies for **wind shear layers** — zones of turbulence, rotor potential, and unpredictable lift structure. The speed component (60%) matters more than direction change (40%) because speed shear is the primary driver of mechanical turbulence.

#### Final formula

```
upper_wind_score = clamp(op − aloft_penalty − coh_pen, 0, 100)
```

---

## 6. Thermal score

**Function**: `thermal_score(row)`
**Weight in potential**: 40%
**Forecast variables**: `temperature_2m`, `dew_point_2m`, `shortwave_radiation`, `sunshine_duration`, `cape`, `cloud_cover_low/mid/high`, `relative_humidity_925/850hPa`, `wind_speed_10m`, `wind_speed_925hPa`

### What it represents

The thermal score is the largest single contributor to potential score. It evaluates the **quality and intensity of convective lift** available during the flying day, combining the energy input (solar radiation), the atmospheric response (lapse rate, CAPE), and the wind modulation of thermal structure.

### Stage 1 — Heat score (70% of raw thermal score)

#### Shortwave radiation sub-score

```
sw_sc = 0             if shortwave ≤ 100 W/m²
sw_sc = 100           if shortwave ≥ 700 W/m²
sw_sc = 100 × (shortwave − 100) / 600    otherwise
```

Shortwave radiation (incoming solar) is the primary driver of surface heating and thermal triggering. Below 100 W/m² solar input is insufficient. Above 700 W/m² the sky is essentially unlimited for thermal production.

#### Sunshine duration sub-score

```
sun_sc = 0             if sunshine = 0 s
sun_sc = 100           if sunshine ≥ 2700 s (45 min)
sun_sc = 100 × sunshine / 2700    otherwise
```

Sunshine duration per hour (seconds of direct sun in the hour) distinguishes intermittent sun breaks from sustained solar heating. Broken cloud with frequent shading produces weaker thermals than an equal shortwave total under thin overcast.

#### Cloud cover sub-score

```
cl_sc = 0.40 × (1 − cloud_low%) + 0.45 × (1 − cloud_mid%) + 0.15 × (1 − cloud_high%)
```

| Layer | Weight | Rationale |
|---|---|---|
| Low cloud (< 2000 m) | 40% | Directly blocks solar heating and may sit below launch |
| Mid cloud (2000–6000 m) | 45% | Most impactful on shortwave reaching the surface |
| High cloud (> 6000 m) | 15% | Cirrus reduces solar but rarely blocks thermals completely |

#### Heat score combination

```
heat_sc = clamp(0.45 × sw_sc + 0.25 × sun_sc + 0.30 × cl_sc, 0, 100)
```

### Stage 2 — Atmospheric response score (30% of raw thermal score)

#### T−Td spread sub-score

```
spread    = temperature_2m − dew_point_2m
spread_sc = 0      if spread ≤ 0°C
spread_sc = 100    if spread ≥ 12°C
spread_sc = 100 × spread / 12    otherwise
```

The temperature–dewpoint spread is the key indicator of boundary-layer moisture. A larger spread means:
- The atmosphere must heat more before condensation begins → thermals reach greater height before cumulus form
- Cloudbase will be higher: `cloudbase ≈ spread × 125 m`
- Blue thermal conditions likely when spread ≥ 9°C with low humidity

A spread below 5°C indicates a humid, potentially capped boundary layer where thermals are weak and cloud bases are low.

#### CAPE sub-score

```
cape_sc = 0      if CAPE ≤ 0 J/kg
cape_sc = 100    if CAPE ≥ 600 J/kg
cape_sc = 100 × CAPE / 600    otherwise
```

Convective Available Potential Energy represents the thermodynamic fuel for convection. CAPE > 600 J/kg indicates energetic thermals with significant vertical extent. It acts as a secondary response indicator (25% weight) alongside spread.

#### Response score

```
resp_sc = clamp(0.75 × spread_sc + 0.25 × cape_sc, 0, 100)
```

#### Raw thermal score

```
t_sc_raw = clamp(0.70 × heat_sc + 0.30 × resp_sc, 0, 100)
```

### Stage 3 — Wind modulation penalties

Wind affects thermal quality in two independent ways, both applied subtractively on `t_sc_raw`.

#### Surface wind speed penalty (0 to −25 pts)

```
if w10 ≤ 4 km/h:   wind_th_pen = 7 × (1 − w10 / 4)     →  max −7 at dead calm
if 4 ≤ w10 ≤ 15:   wind_th_pen = 0                      →  optimal range, no penalty
if w10 > 15 km/h:   wind_th_pen = clamp(25 × (w10 − 15) / 17, 0, 25)  →  max −25 at 32 km/h
```

| Wind | Effect on thermals |
|---|---|
| 0–4 km/h | Surface heating is spatially uniform; thermals form but are weak, scattered, and hard to locate. Boundary layer mixing is insufficient. Small penalty (up to −7). |
| 4–15 km/h | Light breeze creates mechanical mixing that organises and focuses thermal triggers. Optimal range. |
| > 15 km/h | Thermals are progressively swept downwind, compressed in height, and deformed. Above ~20 km/h, rotor zones develop on the lee of ridges. |

#### Low-level shear penalty (0 to −20 pts)

```
shear_lo = |wind_speed_925hPa − wind_speed_10m|

if shear_lo ≤ 8 km/h:    shear_th_pen = 0
if shear_lo ≥ 20 km/h:   shear_th_pen = 20
else:                     shear_th_pen = 20 × (shear_lo − 8) / 12
```

This captures the **boundary-layer wind shear** between the surface (~10 m) and ~750 m (925 hPa). When surface wind and ridge-level wind differ significantly in speed:
- Thermal cores are tilted with height, making centring difficult
- Upwind and downwind faces of the thermal have different climb rates
- Strong shear (> 20 km/h differential) can fragment thermal cores entirely

This shear is distinct from the vertical profile shear captured in `upper_wind_score` (which operates between 925 and 700 hPa).

#### Final thermal score

```
t_sc = clamp(t_sc_raw − wind_th_pen − shear_th_pen, 0, 100)
```

### Thermal regime classification

The regime is derived from `t_sc` (after wind penalties), spread, RH, and cloud, and is used for display and tooltip context.

| Regime | Conditions | Flying implication |
|---|---|---|
| `off` | t_sc < 35, hour < 9 or > 19, shortwave < 120, sunshine < 600 | No thermal activity |
| `cap` | cloud_mid ≥ 85% | Thermal capping — thermals exist but are blocked from developing |
| `blue` | t_sc ≥ 55, spread ≥ 9°C, cloud_low ≤ 20%, mean RH ≤ 45% | Dry thermals, no cumulus markers — requires experience to work |
| `cumulus` | t_sc ≥ 55, spread 5–10°C, mean RH ≥ 45%, cloud_low ≤ 50% | Classic cumulus-marked thermals — most readable conditions |

### Cloudbase estimate

```
cloudbase_m = spread × 125    (Henning formula approximation)
```

Expressed in metres AGL. Used for display and passed to Bernacca's advisory.

---

## 7. Risk score

**Function**: `risk_score(row, site)`
**Role**: generates `risk_pen` subtracted from potential score
**Forecast variables**: `cape`, `precipitation`, `cloud_cover_mid/high`, `relative_humidity_700/600hPa`, `wind_gusts_10m`, `delta_wind_10m`, `delta_gusts_10m`, `delta_wind_925hPa`

### What it represents

The risk score quantifies hazards that are dangerous **regardless of whether launch conditions are otherwise acceptable**. It combines convective/storm potential, sustained gust level, and the rate at which wind conditions are deteriorating. Higher risk score = more danger.

### Component 1 — Storm risk (55% of final)

```
cape_risk  = clamp(100 × CAPE / 800, 0, 100)
cloud_risk = clamp(0.65 × cloud_mid + 0.35 × cloud_hi, 0, 100)
hum_risk   = clamp((RH_700 + RH_600) / 2, 0, 100)
prec_risk  = clamp(100 × precip, 0, 100)   if precip > 0, else 0

storm_risk = clamp(0.35 × cape_risk + 0.25 × cloud_risk + 0.20 × hum_risk + 0.20 × prec_risk, 0, 100)
```

| Sub-component | Rationale |
|---|---|
| CAPE (35%) | The primary thermodynamic fuel for convective development and lightning |
| Mid + high cloud (25%) | Cumulo-nimbus anvils and mid-level convective towers visible in model cloud fields |
| Upper RH at 700/600 hPa (20%) | Moist mid-troposphere supports storm development and reduces energy dissipation |
| Precipitation (20%) | Active precipitation is a direct indicator of convective activity |

#### Why 700/600 hPa for humidity?

Ground-level humidity primarily affects cloudbase. Storm potential requires moisture at mid-tropospheric levels (700–600 hPa, ~3000–4500 m) where updraft entrainment occurs.

### Component 2 — Absolute gust level (20% of final)

```
gust_lvl = jsc(gusts, gust_max × 0.45, gust_max)
         = 0      if gusts ≤ gust_max × 0.45
         = 100    if gusts ≥ gust_max
         = linear between
```

For `gust_max = 30 km/h`: the ramp starts at 13.5 km/h and reaches 100 at 30 km/h.

This component was added to capture **sustained high gust conditions** that are dangerous regardless of whether they are increasing. Without it, a day with steady 27 km/h gusts (just below the veto) would show a misleadingly low risk score.

| Gusts (`gust_max=30`) | gust_lvl | Label |
|---|---|---|
| ≤ 13.5 km/h | 0 | — |
| ~19 km/h | ~33 | "gusts notable" |
| ~25 km/h | ~70 | "gusts high" |
| ≥ 30 km/h | 100 | (veto active) |

### Component 3 — Wind jump risk / trend (25% of final)

```
jsc(d, start, full) = 0    if d ≤ start
                    = 100  if d ≥ full
                    = 100 × (d − start) / (full − start)    otherwise

wjr = clamp(0.20 × jsc(dw10, 3, 10) + 0.35 × jsc(dg10, 4, 12) + 0.45 × jsc(dw925, 3, 10), 0, 100)
```

| Variable | Weight | Start | Full | Rationale |
|---|---|---|---|---|
| `delta_wind_10m` (km/h/h) | 20% | 3 km/h | 10 km/h | Surface wind increasing |
| `delta_gusts_10m` (km/h/h) | 35% | 4 km/h | 12 km/h | Gusts rising fast — most direct gust hazard signal |
| `delta_wind_925hPa` (km/h/h) | 45% | 3 km/h | 10 km/h | Ridge-level flow strengthening — the advance warning of incoming wind |

The 925 hPa trend gets the highest weight because acceleration at ridge level typically precedes surface wind change by 30–60 minutes, giving the earliest warning of deteriorating conditions.

### Final formula

```
risk_score = clamp(0.55 × storm_risk + 0.20 × gust_lvl + 0.25 × wjr, 0, 100)
```

### Penalty application

```
risk_pen = 20 × risk_score / 100
```

Maximum risk penalty is **20 points** on the fly score, applied linearly. This is intentionally moderate — the risk score is a continuous degradation signal, not an on/off switch (hard stops are the veto's job).

---

## 8. Foehn score

**Function**: `foehn_score(row, site)`
**Role**: generates `foehn_pen` subtracted from fly score (after thermal attenuation)
**Forecast variables**: `delta_p_foehn` (derived), `wind_speed/direction_925/850/800/700hPa`

### What it represents

The foehn score measures the probability and intensity of **foehn influence** at the flying site. Foehn is a warm, dry, often violently gusty downslope wind driven by a pressure gradient across a mountain range. Higher foehn score = more foehn = worse flying.

Foehn is qualitatively different from ordinary strong wind: it produces **rotor turbulence** in the lee of ridges that is largely invisible and unpredictable, and its onset can be sudden.

### Pressure gradient component (50%)

```
delta_p = pressure_north_station − pressure_south_station  (hPa)

p_sc = 0      if delta_p ≤ 0
p_sc = 100    if delta_p ≥ foehn_delta_p_max_hpa
p_sc = 100 × delta_p / foehn_delta_p_max_hpa    otherwise
```

The reference stations are site-specific. For example:
- **Montegrappa**: Innsbruck (AT) windward − Bolzano (IT) lee
- **Cavallaria**: Martigny (CH) windward − Aosta (IT) lee

A positive pressure differential drives air from the high-pressure side over the ridge and down the lee slope as foehn.

### Upper flow northerliness component (35%)

```
north_sc(direction, tolerance=70°) = 0     if angular_diff(direction, 0°) ≥ 70°
                                   = 100 × (1 − diff/70°)    otherwise

scores per level = 0.7 × north_sc(direction) + 0.3 × (wind_speed / level_max)
n_sc = 0.35 × score925 + 0.25 × score850 + 0.20 × score800 + 0.20 × score700
```

Foehn is driven by a **northerly to north-northwesterly** synoptic flow over the Alps. Analysing direction at four levels identifies the depth and robustness of the foehn circulation. The 30% speed sub-component confirms that the northerly flow is actually strong enough to sustain foehn dynamics.

### Vertical profile component (15%)

```
deltas = [w850−w925, w800−w850, w700−w800]
gstep(dw) = 20 + min(dw, 20)/20 × 80    if dw > 0,   else 20
vp_sc = mean(gstep for each delta)
```

Foehn wind typically **strengthens with altitude** as the jet-level flow feeds the foehn duct. A profile where upper levels are faster than lower levels supports foehn dynamics. A uniform or decreasing profile with height suggests the wind is not foehn-driven.

### Final formula

```
foehn_score = clamp(0.50 × p_sc + 0.35 × n_sc + 0.15 × vp_sc, 0, 100)
```

### Penalty application

```
foehn_pen = 0     if foehn_score_adj ≤ 40
foehn_pen = 25    if foehn_score_adj ≥ 100
foehn_pen = 25 × (foehn_score_adj − 40) / 60    otherwise
```

Maximum foehn penalty is **25 points** on fly score, active above a score of 40 and reaching maximum at 100. The threshold at 40 acknowledges that minor foehn influence (warm, dry air, light northerly tendency) is not necessarily incompatible with flying.

---

## 9. Potential score

**Function**: computed in `evaluate_hour()`

```
potential_score = clamp(0.25 × launch_score + 0.35 × upper_wind_score + 0.40 × thermal_score, 0, 100)
```

### Component weights rationale

| Component | Weight | Rationale |
|---|---|---|
| thermal_score | 40% | Thermals define the ceiling, range, and quality of the flight. On most Alpine flying days, thermal quality is the primary discriminator between a great day and a mediocre one. |
| upper_wind_score | 35% | The upper wind environment determines whether the flight is safe above ridge height. Excess upper wind makes XC flight impossible regardless of thermal quality. |
| launch_score | 25% | Launch is a necessary condition but not sufficient to define a good day. A difficult launch with excellent conditions aloft still represents a valuable flying opportunity. |

### Why potential is displayed separately

Potential score represents what the day *would* be like without any active vetoes or risk/foehn penalties. It is shown as a dashed line in the fly score panel to help pilots understand whether a vetoed or penalised hour has underlying merit — useful for anticipating windows when conditions may improve.

---

## 10. Fly score

**Function**: computed in `evaluate_hour()`

```
fly_score = clamp(potential_score − risk_pen − foehn_pen, 0, 100)
```

Only computed for non-vetoed hours. For vetoed hours, `fly_score = None`.

The fly score is the single number used in the UI's coloured status bars and for all day-level verdict computations.

---

## 11. Foehn–thermal interaction

**Computed in**: `evaluate_hour()`

Strong thermals partially attenuate foehn influence at pilot level. The physical rationale: active convective mixing in the boundary layer disrupts the laminar low-level foehn flow, and pilots in thermal conditions can climb above the rotor zone quickly. This interaction is most effective at moderate foehn (where convection can compete) and vanishes at extreme foehn (where the pressure gradient overwhelms any convective mixing).

```
_FOEHN_THERMAL_MAX_ATT = 25 pts   # maximum attenuation

thermal_f = clamp(thermal_score / 100, 0, 1)
foehn_f   = clamp(foehn_score_raw / 100, 0, 1)

attenuation = 25 × thermal_f × (1 − foehn_f)
foehn_score_adj = clamp(foehn_score_raw − attenuation, 0, 100)
```

The term `(1 − foehn_f)` ensures the interaction vanishes when foehn is extreme: at `foehn_score = 100`, no attenuation occurs regardless of thermal quality. At moderate foehn (score = 50) and strong thermals (score = 80), attenuation = 25 × 0.80 × 0.50 = 10 points.

The hard veto (pressure gradient threshold) is **never affected** by this interaction.

---

## 12. Day summary and verdict

**Function**: `day_summary(evaluated_hours, day)`
**Evaluated hours**: 06:00–20:00 only (hours outside this range are excluded)

### Usable hours

An hour is **usable** if:
- `veto == False`
- `fly_score ≥ 35`

### Window detection

Usable hours are grouped into **contiguous windows**. A window must span ≥ 2 hours to qualify as "real". Windows of 1 usable hour receive the special verdict "if you must".

### Window scoring

```
window_value = 0.60 × mean_fly + 0.20 × min(duration/5, 1) × 100 + 0.20 × mean_potential
```

The best window is selected by `window_value`. Duration is capped at 5 hours for scoring purposes — beyond 5 hours the bonus is flat.

### Verdict thresholds

| Verdict | Condition |
|---|---|
| **bad idea** | No usable hours (all vetoed or fly_score < 35 everywhere) |
| **if you must** | Usable hours exist but no contiguous 2+ hour window; or best window mean fly < 45 |
| **meh** | Best window mean fly 45–57 |
| **not bad** | Best window mean fly 58–71 |
| **hammer day** | Best window mean fly ≥ 72, duration ≥ 4 h, mean potential ≥ 70 |

### Automatic downgrades

The verdict is **downgraded by one step** if:
- `mean_foehn_score > 90` (extreme foehn risk)
- `mean_foehn_score > 80` AND verdict is "not bad" or "hammer day"
- `mean_risk_score > 75` AND verdict is "meh", "not bad", or "hammer day"

---

## 13. Score interpretation guide

### Fly score

| Range | Meaning |
|---|---|
| 0–34 | Not worth flying (even if not vetoed) |
| 35–44 | Marginal — experienced pilots only, short flights |
| 45–57 | Acceptable — moderate conditions, limited XC potential |
| 58–71 | Good — solid flying day, XC possible |
| 72–100 | Excellent — high potential for long flights |

### Component scores

| Score | launch | upper_wind | thermal | risk | foehn |
|---|---|---|---|---|---|
| 80–100 | Perfect launch window | Ideal upper flow | Strong organised thermals | Negligible risk | No foehn signal |
| 60–79 | Good launch | Acceptable upper wind | Moderate thermals | Low risk | Minor foehn tendency |
| 40–59 | Workable but suboptimal | Some upper wind concern | Weak thermals | Moderate risk | Noticeable foehn |
| 20–39 | Difficult launch | Significant upper wind | Poor thermals | High risk | Strong foehn |
| 0–19 | Near veto conditions | Excessive upper wind | No thermal activity | Very high risk | Severe foehn |

> **Note on risk and foehn**: unlike the other scores, **lower is better** for `risk_score` and **lower is better** for `foehn_score`. A risk of 10 means safe conditions; a foehn of 10 means negligible foehn influence.

### Cloudbase estimate

```
cloudbase ≈ (T2m − Td2m) × 125 m  AGL
```

| Cloudbase | Band | XC implication |
|---|---|---|
| < 800 m | low | Very limited ceiling; local flights only |
| 800–1800 m | medium | Moderate XC potential on good terrain |
| > 1800 m | high | Good XC ceiling; high-altitude routes possible |

---

*Manual generated from `core.py` source. Update when scoring logic changes.*
