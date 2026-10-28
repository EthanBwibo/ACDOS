package com.kq.acdos.data.local

import androidx.room.ColumnInfo
import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Index
import androidx.room.Insert
import androidx.room.PrimaryKey
import androidx.room.Query
import java.time.Instant
import kotlinx.coroutines.flow.Flow

/** pickup_events.event_type; [dbValue] is the server's spelling. */
enum class PickupEventType(val dbValue: String) {
    PICKUP_CONFIRMED("pickup_confirmed"),
    EXCEPTION("exception")
}

/** pickup_events.exception_type. */
enum class PickupExceptionType(val dbValue: String) {
    NO_SHOW("no_show"),
    VEHICLE_ISSUE("vehicle_issue"),
    TRAFFIC_DELAY("traffic_delay")
}

/**
 * Outbox for pickup_events (migration 009). Written on the device first, uploaded
 * later. The device generates [idempotencyKey] and [confirmedAt], so a retried
 * upload can never create a second event. No foreign key to route_stop: an
 * event must outlive its route being purged until it has been uploaded.
 */
@Entity(
    tableName = "pickup_event_outbox",
    indices = [Index("synced_at", "conflict")]
)
data class PendingPickupEventEntity(
    @PrimaryKey @ColumnInfo(name = "idempotency_key") val idempotencyKey: String,
    @ColumnInfo(name = "route_node_id") val routeNodeId: String,
    @ColumnInfo(name = "event_type") val eventType: PickupEventType,
    @ColumnInfo(name = "exception_type") val exceptionType: PickupExceptionType?,
    @ColumnInfo(name = "confirmed_at") val confirmedAt: Instant,
    /** Null until the server has accepted the event. */
    @ColumnInfo(name = "synced_at") val syncedAt: Instant? = null,
    /** Set when the server refused the event for good; it is then never retried. */
    val conflict: String? = null
)

@Dao
interface PendingPickupEventDao {
    @Insert
    suspend fun insert(event: PendingPickupEventEntity)

    /** Events still to upload, oldest first. Synced and conflicted events are excluded. */
    @Query(
        "SELECT * FROM pickup_event_outbox WHERE synced_at IS NULL AND conflict IS NULL " +
            "ORDER BY confirmed_at"
    )
    suspend fun pending(): List<PendingPickupEventEntity>

    @Query("UPDATE pickup_event_outbox SET synced_at = :syncedAt WHERE idempotency_key = :key")
    suspend fun markSynced(key: String, syncedAt: Instant)

    @Query("UPDATE pickup_event_outbox SET conflict = :reason WHERE idempotency_key = :key")
    suspend fun markConflict(key: String, reason: String)

    /** Conflicts for the driver to see, e.g. a stop someone else already confirmed. */
    @Query("SELECT * FROM pickup_event_outbox WHERE conflict IS NOT NULL ORDER BY confirmed_at")
    fun observeConflicts(): Flow<List<PendingPickupEventEntity>>
}
