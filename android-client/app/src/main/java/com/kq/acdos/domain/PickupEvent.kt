package com.kq.acdos.domain

import java.time.Instant

data class PickupEvent(
    val id: String,
    val routeNodeId: String,
    val driverId: String,
    val eventType: PickupEventType,
    val deviceLocalTimestamp: Instant,
    val syncedAt: Instant? = null
)

enum class PickupEventType { CONFIRMED, EXCEPTION_FLAGGED }