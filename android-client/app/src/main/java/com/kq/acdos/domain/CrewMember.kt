package com.kq.acdos.domain

import java.time.Instant

data class CrewMember(
    val id: String,
    val name: String,
    val role: CrewRole,
    val pickupLocation: GeoPoint,
    val dutyReportTime: Instant
)

enum class CrewRole { PILOT, CABIN_CREW }

data class GeoPoint(val latitude: Double, val longitude: Double)