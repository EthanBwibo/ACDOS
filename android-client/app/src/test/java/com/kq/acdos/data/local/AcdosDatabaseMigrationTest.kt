package com.kq.acdos.data.local

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import androidx.test.core.app.ApplicationProvider
import java.io.File
import java.time.Instant
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

private const val DRIVER = "driver-1"
private const val CONFIRMED_AT = 1_793_000_000_000L

/** Gradle runs unit tests from the app module, where the schemas are committed. */
private val SCHEMA_V2 = File("schemas/com.kq.acdos.data.local.AcdosDatabase/2.json")

/**
 * An app update must keep what is on the phone, above all pickups not yet
 * sent. Each test writes a real version 2 database file from its committed
 * schema, then opens it with the app's own builder, as an update does. Room
 * checks the migrated tables against version 3 as it opens them.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class AcdosDatabaseMigrationTest {
    private val context get() = ApplicationProvider.getApplicationContext<Context>()

    @After
    fun tearDown() {
        context.deleteDatabase(AcdosDatabase.NAME)
    }

    private fun SQLiteDatabase.createTables() {
        val schema = JSONObject(SCHEMA_V2.readText()).getJSONObject("database")
        val tables = schema.getJSONArray("entities")
        for (i in 0 until tables.length()) {
            val table = tables.getJSONObject(i)
            val name = table.getString("tableName")
            execSQL(table.getString("createSql").replace("\${TABLE_NAME}", name))
            val indices = table.optJSONArray("indices") ?: continue
            for (j in 0 until indices.length()) {
                val index = indices.getJSONObject(j).getString("createSql")
                execSQL(index.replace("\${TABLE_NAME}", name))
            }
        }
        // Room's own table, with version 2's identity hash.
        val setup = schema.getJSONArray("setupQueries")
        for (i in 0 until setup.length()) execSQL(setup.getString(i))
    }

    private fun SQLiteDatabase.queue(key: String, node: String, type: String, exception: String?) {
        execSQL(
            "INSERT INTO pickup_event_outbox (idempotency_key, driver_id, route_node_id, " +
                "event_type, exception_type, confirmed_at) VALUES (?, ?, ?, ?, ?, ?)",
            arrayOf<Any?>(key, DRIVER, node, type, exception, CONFIRMED_AT)
        )
    }

    /** What version 2 of the app left on the phone. */
    private fun oldDatabase() {
        val file = context.getDatabasePath(AcdosDatabase.NAME)
        file.parentFile?.mkdirs()
        SQLiteDatabase.openOrCreateDatabase(file, null).use { db ->
            db.createTables()
            db.queue("queued", "node-1", PickupEventType.PICKUP_CONFIRMED.name, null)
            db.queue(
                "no-show",
                "node-2",
                PickupEventType.EXCEPTION.name,
                PickupExceptionType.NO_SHOW.name
            )
            db.execSQL(
                "INSERT INTO driver_route (id, plate_number, fetched_at) " +
                    "VALUES ('route-1', 'KDH 101A', $CONFIRMED_AT)"
            )
            db.version = 2
        }
    }

    /** Through the app's own builder, so this fails if it ever wipes on upgrade again. */
    @Test
    fun `an event queued on the old version is still queued after updating`() = runBlocking {
        oldDatabase()

        val updated = AcdosDatabase.build(context)
        val waiting = updated.pendingPickupEventDao().pending(DRIVER)
        updated.close()

        assertEquals(listOf("no-show", "queued"), waiting.map { it.idempotencyKey }.sorted())
        val queued = waiting.first { it.idempotencyKey == "queued" }
        assertEquals("node-1", queued.routeNodeId)
        assertEquals(PickupEventType.PICKUP_CONFIRMED, queued.eventType)
        assertEquals(Instant.ofEpochMilli(CONFIRMED_AT), queued.confirmedAt)
        val noShow = waiting.first { it.idempotencyKey == "no-show" }
        assertEquals(PickupExceptionType.NO_SHOW, noShow.exceptionType)
    }

    @Test
    fun `a route cached on the old version stays, with no arrival time until it refreshes`() =
        runBlocking {
            oldDatabase()

            val updated = AcdosDatabase.build(context)
            val route = updated.driverRouteDao().observeRouteWithStops().first()!!.route
            updated.close()

            assertEquals("KDH 101A", route.plateNumber)
            assertNull(route.plannedArrival)
        }
}
