package com.kq.acdos

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Checks that Moshi's KSP code generator runs with this project's KSP and
 * Kotlin versions, and that snake_case fields from the FastAPI backend map
 * onto camelCase Kotlin properties.
 */
class MoshiCodegenTest {
    @JsonClass(generateAdapter = true)
    data class StopDto(
        @Json(name = "seq_order") val seqOrder: Int,
        @Json(name = "estimated_arrival") val estimatedArrival: String
    )

    @Test
    fun generatedAdapter_parsesSnakeCaseJson() {
        val moshi = Moshi.Builder().build()
        // Fails with "Cannot serialize Kotlin type ... Reflective serialization
        // of Kotlin classes without using kotlin-reflect has undefined and
        // unexpected behavior" if the generated adapter is missing.
        val adapter = moshi.adapter(StopDto::class.java)

        val json = """{"seq_order": 2, "estimated_arrival": "2026-11-01T03:40:00Z"}"""

        val stop = adapter.fromJson(json)

        val expected = StopDto(seqOrder = 2, estimatedArrival = "2026-11-01T03:40:00Z")
        assertEquals(expected, stop)
    }
}
