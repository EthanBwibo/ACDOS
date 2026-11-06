package com.kq.acdos.ui

import com.kq.acdos.data.NetworkKind
import org.junit.Assert.assertEquals
import org.junit.Test

class StatusBannersTest {
    @Test
    fun `offline hides the failure it would only repeat`() {
        assertEquals(BannerState(true, null), bannerState(NetworkKind.NONE, "Couldn't load"))
    }

    @Test
    fun `online shows the failure`() {
        val state = bannerState(NetworkKind.WIFI, "Couldn't load")

        assertEquals(BannerState(false, "Couldn't load"), state)
    }

    @Test
    fun `online with nothing wrong shows neither`() {
        assertEquals(BannerState(false, null), bannerState(NetworkKind.MOBILE, null))
    }
}
