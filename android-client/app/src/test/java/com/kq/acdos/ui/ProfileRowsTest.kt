package com.kq.acdos.ui

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.kq.acdos.R
import com.kq.acdos.auth.AppRole
import com.kq.acdos.data.local.CrewPickupEntity
import com.kq.acdos.data.local.MyProfileEntity
import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** What the Profile screen (#231) shows for each role, from the cache. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class ProfileRowsTest {
    private val context get() = ApplicationProvider.getApplicationContext<Context>()
    private val now = Instant.parse("2026-11-17T03:00:00Z") // 06:00 EAT

    private fun rows(role: AppRole, details: MyProfileEntity?, pickup: CrewPickupEntity? = null) =
        profileRows(role, details, pickup, now, context::getString).map {
            context.getString(it.label) to it.value
        }

    @Test
    fun crew_seeRoleZoneAndTheirNextPickup() {
        val details =
            MyProfileEntity(crewRole = "cabin_crew", homeZone = "Westlands", fetchedAt = now)
        val pickup = CrewPickupEntity(
            pickupRequestId = "p1",
            estimatedPickup = now.plusSeconds(3600),
            reportTime = now.plusSeconds(7200),
            plateNumber = "KDA 001A",
            fetchedAt = now,
            status = "assigned"
        )

        assertEquals(
            listOf(
                "Crew role" to "Cabin crew",
                "Home zone" to "Westlands",
                "Next pickup" to "07:00 EAT",
                "Pickup status" to "Planned"
            ),
            rows(AppRole.CREW, details, pickup)
        )
    }

    @Test
    fun crew_withNothingLoadedOrToCome() {
        assertEquals(
            listOf(
                "Crew role" to NOT_LOADED,
                "Home zone" to NOT_LOADED,
                "Next pickup" to context.getString(R.string.profile_no_pickup),
                "Pickup status" to NOT_LOADED
            ),
            rows(AppRole.CREW, details = null)
        )
    }

    @Test
    fun theDispatcher_seesTheirEmail() {
        val details = MyProfileEntity(email = "grace@acdos.test", fetchedAt = now)

        assertEquals(listOf("Email" to "grace@acdos.test"), rows(AppRole.DISPATCHER, details))
        assertEquals(listOf("Email" to NOT_LOADED), rows(AppRole.DISPATCHER, null))
    }

    @Test
    fun drivers_seeTheirVan() {
        val details = MyProfileEntity(
            vehiclePlate = "KDA 001A",
            vehicleSeats = 14,
            vehicleStatus = "broken_down",
            fetchedAt = now
        )

        assertEquals(
            listOf(
                "Vehicle" to "KDA 001A",
                "Seats" to "14",
                "Vehicle status" to "Broken down"
            ),
            rows(AppRole.DRIVER, details)
        )
    }

    @Test
    fun aDriverWithNoVan_isToldSo_notThatNothingLoaded() {
        val noVan = rows(AppRole.DRIVER, MyProfileEntity(fetchedAt = now)).first()
        val never = rows(AppRole.DRIVER, details = null).first()

        assertEquals("Vehicle" to context.getString(R.string.crew_no_vehicle), noVan)
        assertEquals("Vehicle" to NOT_LOADED, never)
    }
}
