package com.kq.acdos.domain

data class TripRecord(
    val id: String,
    val routeId: String,
    val actualDurationSeconds: Long,
    val dayOfWeek: Int,
    val hourOfDay: Int,
    val routeCorridor: String
)