package com.kq.acdos.data.remote

import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Test

/** Timestamps as the backend sends them: "Z" or an offset, with or without a fraction. */
class InstantAdapterTest {
    private val adapter = ApiClient.moshi.adapter(Instant::class.java)

    private fun parse(value: String): Instant = adapter.fromJson("\"$value\"")!!

    @Test
    fun utcWithFraction() {
        val parsed = parse("2026-10-30T06:50:34.037197Z")

        assertEquals(Instant.ofEpochSecond(1_793_343_034, 37_197_000), parsed)
    }

    @Test
    fun utcWithoutFraction() {
        assertEquals(Instant.ofEpochSecond(1_793_343_034), parse("2026-10-30T06:50:34Z"))
    }

    @Test
    fun nairobiOffsetIsTheSameInstant() {
        assertEquals(parse("2026-10-30T06:50:34Z"), parse("2026-10-30T09:50:34+03:00"))
        assertEquals(
            parse("2026-10-30T06:50:34.5Z"),
            parse("2026-10-30T09:50:34.500+03:00")
        )
    }

    @Test
    fun writesUtcIso8601() {
        val instant = Instant.ofEpochSecond(1_793_343_034, 37_197_000)

        assertEquals("\"2026-10-30T06:50:34.037197Z\"", adapter.toJson(instant))
    }
}
