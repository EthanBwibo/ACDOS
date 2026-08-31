package com.kq.acdos.domain

import java.time.Instant

data class RouteNode(
    val id: String,
    val sequenceIndex: Int,
    val pickupRequestId: String,
    val estimatedArrivalTime: Instant,
    val actualArrivalTime: Instant? = null
)