package com.kq.acdos.ui.driver

import com.kq.acdos.R
import com.kq.acdos.data.RefreshResult
import org.junit.Assert.assertEquals
import org.junit.Test

/** What the driver is told after a refresh, for a pull and for a refresh on start. */
class RefreshMessageTest {
    @Test
    fun pullToRefresh_explainsEveryFailure() {
        assertEquals(R.string.route_refresh_offline, refreshMessage(RefreshResult.OFFLINE, true))
        assertEquals(R.string.route_refresh_failed, refreshMessage(RefreshResult.FAILED, true))
        assertEquals(
            R.string.route_refresh_sign_in_again,
            refreshMessage(RefreshResult.SIGN_IN_AGAIN, true)
        )
        assertEquals(
            R.string.route_refresh_not_allowed,
            refreshMessage(RefreshResult.NOT_ALLOWED, true)
        )
    }

    @Test
    fun refreshOnStart_staysQuietUnlessSigningInAgainOrTheRoleCanHelp() {
        assertEquals(null, refreshMessage(RefreshResult.OFFLINE, false))
        assertEquals(null, refreshMessage(RefreshResult.FAILED, false))
        assertEquals(
            R.string.route_refresh_sign_in_again,
            refreshMessage(RefreshResult.SIGN_IN_AGAIN, false)
        )
        assertEquals(
            R.string.route_refresh_not_allowed,
            refreshMessage(RefreshResult.NOT_ALLOWED, false)
        )
    }

    @Test
    fun successAndThrottle_sayNothing() {
        val silent = listOf(RefreshResult.UPDATED, RefreshResult.NO_ROUTE, RefreshResult.THROTTLED)
        for (result in silent) {
            assertEquals("$result", null, refreshMessage(result, true))
            assertEquals("$result", null, refreshMessage(result, false))
        }
    }
}
