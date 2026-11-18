package com.kq.acdos.ui

import androidx.annotation.StringRes
import com.kq.acdos.R
import com.kq.acdos.auth.AppRole
import com.kq.acdos.data.local.CrewPickupEntity
import com.kq.acdos.data.local.MyProfileEntity
import com.kq.acdos.data.remote.PickupRequestStatusDto
import com.kq.acdos.data.remote.VehicleStatusDto
import com.kq.acdos.ui.dispatcher.pickupStatusLabel
import com.kq.acdos.ui.dispatcher.vehicleStatusLabel
import java.time.Instant

/** One line of the Profile screen: a label and its value. */
data class ProfileRow(@StringRes val label: Int, val value: String)

/** Shown for a detail the phone has never loaded. */
const val NOT_LOADED = "—"

/**
 * The Profile screen's details (#231, #249), all from Room so they show with
 * no signal. [details] is null until GET /crew/me or /drivers/me has answered
 * once, or for the dispatcher until the email was first read; [pickup] is the crew member's cached next pickup, null when there is
 * none to come. [text] looks up a string.
 */
fun profileRows(
    role: AppRole,
    details: MyProfileEntity?,
    pickup: CrewPickupEntity?,
    now: Instant,
    text: (Int) -> String
): List<ProfileRow> = when (role) {
    AppRole.CREW -> listOf(
        ProfileRow(R.string.profile_crew_role, details?.crewRole?.let(::humanise) ?: NOT_LOADED),
        ProfileRow(R.string.profile_home_zone, details?.homeZone ?: NOT_LOADED),
        ProfileRow(
            R.string.profile_next_pickup,
            when {
                pickup == null -> text(R.string.profile_no_pickup)
                pickup.estimatedPickup == null -> text(R.string.crew_pickup_time_unknown)
                else -> Times.clockWithDay(pickup.estimatedPickup, now)
            }
        ),
        ProfileRow(
            R.string.profile_pickup_status,
            pickup?.status?.let { status ->
                PickupRequestStatusDto.entries.find { it.name.lowercase() == status }
            }?.let { text(pickupStatusLabel(it)) } ?: NOT_LOADED
        )
    )

    AppRole.DRIVER -> listOf(
        ProfileRow(
            R.string.profile_vehicle,
            when {
                details == null -> NOT_LOADED
                else -> details.vehiclePlate ?: text(R.string.crew_no_vehicle)
            }
        ),
        ProfileRow(R.string.profile_seats, details?.vehicleSeats?.toString() ?: NOT_LOADED),
        ProfileRow(
            R.string.profile_vehicle_status,
            details?.vehicleStatus?.let { status ->
                VehicleStatusDto.entries.find { it.name.lowercase() == status }
            }?.let { text(vehicleStatusLabel(it)) } ?: NOT_LOADED
        )
    )

    AppRole.DISPATCHER -> listOf(
        ProfileRow(R.string.profile_email, details?.email ?: NOT_LOADED)
    )
}

/** "cabin_crew" as the roster has it, shown as "Cabin crew". */
fun humanise(value: String): String =
    value.replace('_', ' ').trim().replaceFirstChar { it.uppercaseChar() }
