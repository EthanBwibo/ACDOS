package com.kq.acdos.ui.driver

import com.kq.acdos.data.local.PickupEventType
import com.kq.acdos.data.local.PickupExceptionType
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Decides whether a stop's status chip is green or amber. */
class StopProgressTest {
    private val accepted = StopProgress(
        type = PickupEventType.PICKUP_CONFIRMED,
        exception = null,
        sent = true,
        conflict = null,
        done = true
    )

    @Test
    fun `an accepted pickup is good news`() {
        assertTrue(accepted.isGoodNews)
    }

    @Test
    fun `a pickup still waiting to send is not`() {
        assertFalse(accepted.copy(sent = false).isGoodNews)
    }

    @Test
    fun `a pickup the server refused is not`() {
        assertFalse(accepted.copy(conflict = "route_superseded").isGoodNews)
    }

    @Test
    fun `a reported problem is not`() {
        val problem = accepted.copy(
            type = PickupEventType.EXCEPTION,
            exception = PickupExceptionType.NO_SHOW
        )

        assertFalse(problem.isGoodNews)
    }
}
