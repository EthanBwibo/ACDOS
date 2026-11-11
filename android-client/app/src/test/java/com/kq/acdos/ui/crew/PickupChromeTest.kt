package com.kq.acdos.ui.crew

import com.kq.acdos.R
import com.kq.acdos.data.local.CrewPickupEntity
import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Test

/** "No pickup to come" must only ever mean the server said so. */
class PickupChromeTest {
    private val pickup = CrewPickupState.Pickup(
        CrewPickupEntity("p1", Instant.EPOCH, Instant.EPOCH, "KDH 101A", Instant.EPOCH)
    )
    private val failed = R.string.crew_refresh_offline

    @Test
    fun `an empty cache spins until the first answer`() {
        assertEquals(
            PickupChrome(spinner = true, showEmpty = false, error = null),
            pickupChrome(CrewPickupState.NoPickup, true, null, false)
        )
    }

    @Test
    fun `a failed first load says so, not that there is no pickup`() {
        assertEquals(
            PickupChrome(spinner = false, showEmpty = false, error = failed),
            pickupChrome(CrewPickupState.NoPickup, false, failed, false)
        )
    }

    @Test
    fun `no pickup is said only after the server answers`() {
        assertEquals(
            PickupChrome(spinner = false, showEmpty = true, error = null),
            pickupChrome(CrewPickupState.NoPickup, false, null, false)
        )
    }

    @Test
    fun `a cached pickup stays quiet when a refresh fails`() {
        assertEquals(
            PickupChrome(spinner = false, showEmpty = false, error = null),
            pickupChrome(pickup, false, failed, false)
        )
    }

    @Test
    fun `a pull spins over a cached pickup`() {
        assertEquals(true, pickupChrome(pickup, false, null, true).spinner)
    }
}
