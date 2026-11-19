package com.kq.acdos.ui.dispatcher

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.kq.acdos.data.remote.LeftOutReasonDto
import com.kq.acdos.data.remote.LeftOutVehicleDto
import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** The left-out vans' wording on the Plan tab and Re-plan (#274), in Nairobi time. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class LeftOutTextTest {
    private val context: Context = ApplicationProvider.getApplicationContext()

    private fun van(plate: String, from: String, to: String) = LeftOutVehicleDto(
        "id-$plate",
        plate,
        LeftOutReasonDto.LATER_ROUTE,
        Instant.parse("2026-11-20T$from:00Z"),
        Instant.parse("2026-11-20T$to:00Z")
    )

    @Test
    fun eachVan_namesItsLaterRoute_inNairobiTime() {
        // 05:00–07:00 UTC is 08:00–10:00 in Nairobi.
        val text = context.leftOutText(
            listOf(van("KDX 004", "05:00", "07:00"), van("KDX 009", "08:30", "10:30"))
        )

        assertEquals(
            "KDX 004 left out: has the 08:00–10:00 route\n" +
                "KDX 009 left out: has the 11:30–13:30 route",
            text
        )
    }

    @Test
    fun noVanLeftOut_showsNothing() {
        assertNull(context.leftOutText(emptyList()))
    }
}
