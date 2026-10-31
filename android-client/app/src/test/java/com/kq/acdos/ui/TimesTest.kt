package com.kq.acdos.ui

import java.time.Instant
import java.util.TimeZone
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test

/** Times are Nairobi time whatever zone the phone is set to. */
class TimesTest {
    private lateinit var phoneZone: TimeZone

    @Before
    fun setUp() {
        phoneZone = TimeZone.getDefault()
        // A crew member just back from London, phone not yet switched over.
        TimeZone.setDefault(TimeZone.getTimeZone("Europe/London"))
    }

    @After
    fun tearDown() = TimeZone.setDefault(phoneZone)

    @Test
    fun clock_isNairobiTimeLabelledEat() {
        assertEquals("06:50 EAT", Times.clock(Instant.parse("2026-10-30T03:50:34.037197Z")))
    }

    @Test
    fun clock_is24HourAcrossMidnight() {
        assertEquals("00:05 EAT", Times.clock(Instant.parse("2026-10-30T21:05:00Z")))
        assertEquals("15:00 EAT", Times.clock(Instant.parse("2026-10-30T12:00:00Z")))
    }
}
