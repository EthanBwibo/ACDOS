package com.kq.acdos.domain

import java.time.Instant

data class PickupRequest(
    val id: String,
    val crewMemberId: String,
    val pickupLocation: GeoPoint,
    val hardDeadline: Instant,
    val status: PickupRequestStatus
)

enum class PickupRequestStatus { PENDING, ASSIGNED, CONFIRMED, MISSED }