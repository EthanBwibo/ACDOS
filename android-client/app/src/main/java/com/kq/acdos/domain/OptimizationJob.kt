package com.kq.acdos.domain

import java.time.Instant

data class OptimizationJob(
    val id: String,
    val triggeredAt: Instant,
    val trigger: OptimizationTrigger,
    val resultingRoutes: List<Route> = emptyList(),
    val status: OptimizationJobStatus
)

enum class OptimizationTrigger { SCHEDULED, STANDBY_ACTIVATION, VEHICLE_BREAKDOWN, FLIGHT_AMENDMENT, MANUAL }
enum class OptimizationJobStatus { RUNNING, COMPLETE, FAILED }