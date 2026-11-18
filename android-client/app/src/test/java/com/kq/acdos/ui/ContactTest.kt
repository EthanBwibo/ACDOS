package com.kq.acdos.ui

import android.content.Intent
import com.kq.acdos.data.DriverContact
import com.kq.acdos.data.local.CrewPickupEntity
import com.kq.acdos.ui.crew.CrewPickupState
import com.kq.acdos.ui.crew.driverFor
import com.kq.acdos.ui.driver.firstName
import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Driver and crew contact (#255): the dial intent, and whose number a screen may show. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class ContactTest {
    private val t0 = Instant.parse("2026-11-21T02:00:00Z")

    private fun showing(id: String) = CrewPickupState.Pickup(
        CrewPickupEntity(
            pickupRequestId = id,
            estimatedPickup = t0,
            reportTime = t0.plusSeconds(5400),
            plateNumber = "KDA 002T",
            fetchedAt = t0
        ),
        null
    )

    @Test
    fun call_opensTheDialerWithTheNumber_andNeedsNoPermission() {
        val intent = dialIntent("+254700000101")

        assertEquals(Intent.ACTION_DIAL, intent.action)
        assertEquals("tel:+254700000101", intent.data.toString())
    }

    @Test
    fun theDriverShown_isTheOneForThePickupOnScreen() {
        val contact = DriverContact("p1", "Peter", "+254700000101")

        assertEquals(contact, driverFor(showing("p1"), contact))
    }

    @Test
    fun aContactLeftFromAnotherPickup_isNeverShown() {
        val other = DriverContact("p0", "Peter", "+254700000101")

        assertNull(driverFor(showing("p1"), other))
        assertNull(driverFor(CrewPickupState.NoPickup, other))
    }

    @Test
    fun callButtonsUseTheFirstName() {
        assertEquals("Amina", firstName("Amina Otieno"))
        assertEquals("Amina", firstName("  Amina  "))
    }
}
