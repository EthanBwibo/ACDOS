package com.kq.acdos.ui.driver

import android.content.ActivityNotFoundException
import android.content.Intent
import java.util.Locale
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** "Navigate" (#228): Google Maps turn-by-turn first, any maps app second. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class NavigationTest {
    private val intents = navigationIntents(-1.2921, 36.8219)

    @Test
    fun `Google Maps is asked for turn-by-turn first`() {
        val google = intents[0]

        assertEquals(Intent.ACTION_VIEW, google.action)
        assertEquals("google.navigation:q=-1.29210,36.82190", google.dataString)
        assertEquals(GOOGLE_MAPS_PACKAGE, google.`package`)
    }

    @Test
    fun `any maps app is the fallback, with the stop pinned`() {
        val geo = intents[1]

        assertEquals("geo:-1.29210,36.82190?q=-1.29210,36.82190", geo.dataString)
        assertNull("no package, so any maps app can answer", geo.`package`)
        assertEquals(2, intents.size)
    }

    @Test
    fun `coordinates keep a decimal point in any language`() {
        val before = Locale.getDefault()
        Locale.setDefault(Locale.FRANCE)
        try {
            assertEquals(
                "google.navigation:q=-1.29210,36.82190",
                navigationIntents(-1.2921, 36.8219)[0].dataString
            )
        } finally {
            Locale.setDefault(before)
        }
    }

    @Test
    fun `with Google Maps installed, only it is started`() {
        val started = mutableListOf<Intent>()

        assertTrue(startFirst(intents) { started += it })

        assertEquals(listOf(intents[0]), started)
    }

    @Test
    fun `without Google Maps, the plain maps link is started`() {
        val started = mutableListOf<Intent>()

        val ok = startFirst(intents) {
            if (it.`package` == GOOGLE_MAPS_PACKAGE) throw ActivityNotFoundException()
            started += it
        }

        assertTrue(ok)
        assertEquals(listOf(intents[1]), started)
    }

    @Test
    fun `with no maps app at all, it says so`() {
        assertFalse(startFirst(intents) { throw ActivityNotFoundException() })
    }
}
