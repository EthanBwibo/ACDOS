package com.kq.acdos.ui.dispatcher

import android.content.Context
import android.net.Uri
import androidx.test.core.app.ApplicationProvider
import java.io.File
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Download template (#254): the bundled file, and saving it where the dispatcher picked. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class RosterTemplateTest {
    private val context get() = ApplicationProvider.getApplicationContext<Context>()

    private fun bundled() = context.assets.open(ROSTER_TEMPLATE).use { it.readBytes() }

    @Test
    fun theBundledTemplate_isTheOneInDocs() {
        val path =
            System.getProperty("acdos.rosterTemplate") ?: error("acdos.rosterTemplate is not set")

        assertArrayEquals(File(path).readBytes(), bundled())
    }

    @Test
    fun theTemplate_hasTheImportsHeadersAndTwoExampleRows() {
        val lines = String(bundled()).trim().lines()

        val headers = "staff_no,name,crew_role,pickup_location,report_time,request_type,set_home"
        assertEquals(headers, lines.first())
        assertEquals(3, lines.size)
    }

    @Test
    fun saving_writesTheTemplateToThePickedFile() {
        val target = File(context.cacheDir, "saved.csv")

        assertTrue(saveRosterTemplate(context, Uri.fromFile(target)))

        assertArrayEquals(bundled(), target.readBytes())
    }

    @Test
    fun aPlaceThatCantBeWritten_isReportedNotThrown() {
        val missing = File(context.cacheDir, "no/such/folder/saved.csv")

        assertFalse(saveRosterTemplate(context, Uri.fromFile(missing)))
    }
}
