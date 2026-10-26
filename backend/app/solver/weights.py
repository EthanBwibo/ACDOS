"""Fitness weights, per problem (#99): crew transport or Solomon's VRPTW.

The terms are explained in fitness.py. CREW is the ACDOS objective: tiers that
keep every crew member on time first, then trade vehicles against driving and
waiting. SOLOMON is the standard objective for Solomon's (1987) benchmark
instances (#13): every time window met, then fewest vehicles, then shortest
total distance, which is how the published best-known solutions are ranked.

A Problem carries one of these (Problem.weights, CREW by default), so the same
solver code costs either kind of instance.
"""

import math
from dataclasses import dataclass

# --- Crew weights. The values and their reasons, unchanged from fitness.py
# before #99; fitness.py still exports them under these names.

# Per crew member left without a vehicle. One outweighs about 278 h of total
# lateness (1e10 / 10,000 / 3600).
UNASSIGNED_WEIGHT = 1e10
# Per second past report time, per crew member. One minute late (600,000)
# outweighs about 10 vehicles plus about 150 h of T + W.
LATENESS_WEIGHT = 10_000.0
# Per crew member who is late at all, on top of their seconds late: equal to
# 30 min of lateness. Each late crew member is a separate flight-delay risk, so
# making an on-time crew member late must cost more than adding the same
# seconds to someone already late. At 6,000,000 (10 min), #12's lost-cause
# instance tied exactly between the two (#75); sensitivity run planned (#14).
LATE_CREW_WEIGHT = 18_000_000.0
# Per second of buffer eaten, per crew member. The whole 15 min buffer
# (90,000) costs about 25 vehicles, and still less than a minute late.
BUFFER_WEIGHT = 100.0
# A crew member's ride (JKIA arrival minus arrival at their stop) is free up to
# 90 min; each second beyond costs RIDE_WEIGHT, the buffer's tier: 15 min over
# (90,000) costs about 25 vehicles and less than a minute late. Both are in the
# #14 sensitivity runs.
MAX_RIDE_SEC = 5400.0
RIDE_WEIGHT = 100.0
# Per vehicle used: worth 1 h of T + W. Sensitivity check at 1,800 and 7,200
# planned for the results chapter.
VEHICLE_WEIGHT = 3_600.0
# Per second of vehicle time (T) or crew waiting beyond the buffer (W).
TIME_WEIGHT = 1.0
# Latest departure aims to have everyone at JKIA this long before the earliest
# report time on board, as slack for traffic the travel time function missed.
REPORT_BUFFER_SEC = 900.0


@dataclass(frozen=True)
class FitnessWeights:
    unassigned: float  # per pickup left without a vehicle (U)
    lateness: float  # per second late, per pickup (L)
    late_crew: float  # per pickup late at all (K_late)
    buffer: float  # per second of report buffer eaten (B)
    ride: float  # per second of ride beyond max_ride_sec (R)
    max_ride_sec: float
    vehicle: float  # per vehicle used (K)
    time: float  # per second of vehicle time (T) and of waiting at the destination (W)
    distance: float  # per unit of distance driven (D)
    report_buffer_sec: float
    # True: each vehicle leaves as late as it can (crew are not collected hours
    # early). False: it leaves at available_from, the standard VRPTW schedule.
    latest_departure: bool


CREW = FitnessWeights(
    unassigned=UNASSIGNED_WEIGHT,
    lateness=LATENESS_WEIGHT,
    late_crew=LATE_CREW_WEIGHT,
    buffer=BUFFER_WEIGHT,
    ride=RIDE_WEIGHT,
    max_ride_sec=MAX_RIDE_SEC,
    vehicle=VEHICLE_WEIGHT,
    time=TIME_WEIGHT,
    # Driving already costs through T, in seconds; D is for Solomon.
    distance=0.0,
    report_buffer_sec=REPORT_BUFFER_SEC,
    latest_departure=True,
)

# Solomon instances: time windows are hard constraints, then vehicles, then
# distance (sum of leg lengths, not counting waiting or service). The tiers, in
# Solomon's units (a 100-customer instance's total distance is under 2,000):
# - one unit late (1e7, plus 1e7 for being late at all) outweighs any number
#   of vehicles (at most 25 x 1e5 = 2.5e6) plus distance;
# - one vehicle (1e5) outweighs any total distance.
# There is no report time, so no buffer, ride cap or waiting cost.
SOLOMON = FitnessWeights(
    unassigned=UNASSIGNED_WEIGHT,
    lateness=1e7,
    late_crew=1e7,
    buffer=0.0,
    ride=0.0,
    max_ride_sec=math.inf,
    vehicle=1e5,
    time=0.0,
    distance=1.0,
    report_buffer_sec=0.0,
    latest_departure=False,
)
