package com.kq.acdos.data

import com.kq.acdos.data.remote.DispatcherPickupDto
import java.time.Duration
import java.time.Instant

/**
 * The widest span of report times one plan may cover. The server refuses a
 * wider job with planning_window_too_wide. This is the app's only copy of the
 * limit, so a wave never asks for more than the server allows.
 */
val MAX_PLAN_SPAN: Duration = Duration.ofHours(4)

/** A gap longer than this between two report times starts a new wave. */
val WAVE_GAP: Duration = Duration.ofMinutes(60)

/** Pickups planned together: report times from [first] to [last]. */
data class PlanWave(val first: Instant, val last: Instant, val pickupIds: List<String>)

/**
 * [pickups] in waves, earliest first. In report-time order, a pickup starts a
 * new wave when it is more than [WAVE_GAP] after the one before it, or when
 * joining would make the wave span more than [MAX_PLAN_SPAN]. Each pickup is
 * in exactly one wave.
 */
fun planWaves(pickups: List<DispatcherPickupDto>): List<PlanWave> {
    val waves = mutableListOf<PlanWave>()
    for (pickup in pickups.sortedWith(compareBy({ it.reportTime }, { it.id }))) {
        val wave = waves.lastOrNull()
        val at = pickup.reportTime
        if (wave != null &&
            Duration.between(wave.last, at) <= WAVE_GAP &&
            Duration.between(wave.first, at) <= MAX_PLAN_SPAN
        ) {
            waves[waves.lastIndex] = wave.copy(last = at, pickupIds = wave.pickupIds + pickup.id)
        } else {
            waves += PlanWave(at, at, listOf(pickup.id))
        }
    }
    return waves
}

/** The day's unplanned pickups in waves: the ones a first plan takes. */
fun planWaves(board: DayBoard): List<PlanWave> {
    val unplanned = unplannedPickups(board).toSet()
    return planWaves(board.pickups.filter { it.id in unplanned })
}
