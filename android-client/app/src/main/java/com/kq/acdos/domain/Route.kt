package com.kq.acdos.domain

data class Route(
    val id: String,
    val vehicleId: String,
    val nodes: List<RouteNode>,
    val optimizationJobId: String
)