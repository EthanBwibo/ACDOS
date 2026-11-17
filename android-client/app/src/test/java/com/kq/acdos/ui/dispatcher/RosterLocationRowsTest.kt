package com.kq.acdos.ui.dispatcher

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.kq.acdos.data.remote.RejectReasonDto
import com.kq.acdos.data.remote.RejectedRowDto
import com.kq.acdos.data.remote.RosterImportResultDto
import com.kq.acdos.data.remote.RowLocationDto
import java.util.Locale
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** The dry run's pickup points in Import roster (#245), as docs/roster_import.md's sample gives them. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class RosterLocationRowsTest {
    private val context get() = ApplicationProvider.getApplicationContext<Context>()
    private lateinit var locale: Locale

    @Before
    fun setUp() {
        locale = Locale.getDefault()
        Locale.setDefault(Locale.UK)
    }

    @After
    fun tearDown() = Locale.setDefault(locale)

    private fun result(rejected: List<RejectedRowDto>) = RosterImportResultDto(
        dryRun = true,
        rows = 10,
        crewCreated = 2,
        crewUpdated = 0,
        pickupsCreated = 5,
        rowsRejected = rejected.size,
        rejected = rejected,
        locations = listOf(
            RowLocationDto(2, "KQ10231", "Kilimani, Nairobi", 0.4),
            RowLocationDto(4, "KQ10457", "Westlands, Nairobi", 1.3),
            RowLocationDto(8, "KQ11290", "Runda, Nairobi", 129.9)
        )
    )

    @Test
    fun eachPoint_showsItsZoneAndDistance_andTheOneRejectedSaysItIsOutside() {
        val outside = RejectedRowDto(
            8,
            "KQ11290",
            RejectReasonDto.OUTSIDE_PICKUP_ZONES,
            "over 10 km from every pickup zone"
        )

        val rows = locationRows(result(listOf(outside)), context::getString)

        assertEquals(
            listOf(
                LocationRow("2", "Kilimani, Nairobi", "KQ10231 · 0.4 km from the zone"),
                LocationRow("4", "Westlands, Nairobi", "KQ10457 · 1.3 km from the zone"),
                LocationRow(
                    "8",
                    "Runda, Nairobi",
                    "KQ11290 · 129.9 km: outside the pickup zones"
                )
            ),
            rows
        )
    }

    @Test
    fun outsideComesFromTheRejectedRows_notTheRoundedDistance() {
        val atTheLimit = result(emptyList()).copy(
            locations = listOf(RowLocationDto(2, "KQ1", "Karen, Nairobi", 10.0)),
            rejected = listOf(
                RejectedRowDto(2, "KQ1", RejectReasonDto.OUTSIDE_PICKUP_ZONES, "over 10 km")
            )
        )

        val row = locationRows(atTheLimit, context::getString).single()

        assertEquals("KQ1 · 10.0 km: outside the pickup zones", row.detail)
    }

    @Test
    fun aResultWithNoPoints_listsNone() {
        val none = result(emptyList()).copy(locations = emptyList())

        assertEquals(emptyList<LocationRow>(), locationRows(none, context::getString))
    }
}
