package com.kq.acdos.data.local

import androidx.room.ColumnInfo
import androidx.room.Dao
import androidx.room.Embedded
import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.Insert
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Relation
import androidx.room.Transaction
import java.time.Instant
import kotlinx.coroutines.flow.Flow

/**
 * The driver's current active route: at most one row. Completed and superseded
 * routes are not kept, see [DriverRouteDao.purgeRoute].
 */
@Entity(tableName = "driver_route")
data class RouteEntity(
    @PrimaryKey val id: String,
    @ColumnInfo(name = "plate_number") val plateNumber: String,
    @ColumnInfo(name = "fetched_at") val fetchedAt: Instant
)

/**
 * One pickup on the driver's route: a stop of GET /drivers/me/route (#52),
 * kept so the Route tab works offline. Only what the screen shows: no crew id,
 * phone or address text, and no per-crew deadline (drivers don't see them).
 */
@Entity(
    tableName = "route_stop",
    foreignKeys = [
        ForeignKey(
            entity = RouteEntity::class,
            parentColumns = ["id"],
            childColumns = ["route_id"],
            onDelete = ForeignKey.CASCADE
        )
    ],
    indices = [Index("route_id")]
)
data class RouteStopEntity(
    /** route_nodes.id, which pickup events refer to. */
    @PrimaryKey @ColumnInfo(name = "route_node_id") val routeNodeId: String,
    @ColumnInfo(name = "route_id") val routeId: String,
    @ColumnInfo(name = "seq_order") val seqOrder: Int,
    @ColumnInfo(name = "crew_name") val crewName: String,
    /** Nearest pickup zone, e.g. "Westlands, Nairobi"; null when the backend has none. */
    @ColumnInfo(name = "zone_label") val zoneLabel: String?,
    /** The live plan's time at this stop. */
    @ColumnInfo(name = "scheduled_pickup") val scheduledPickup: Instant,
    /** Null until live tracking can estimate it; shown instead of [scheduledPickup] when set. */
    val eta: Instant?,
    @ColumnInfo(name = "pickup_lat") val pickupLat: Double,
    @ColumnInfo(name = "pickup_lon") val pickupLon: Double
)

/** The cached route with its stops, read together (see [DriverRouteDao.observeRouteWithStops]). */
data class RouteWithStops(
    @Embedded val route: RouteEntity,
    @Relation(parentColumn = "id", entityColumn = "route_id")
    val stops: List<RouteStopEntity>
)

@Dao
interface DriverRouteDao {
    /**
     * The route and its stops in one read, so a replaced route shows up as one
     * change: never the old route with its stops already deleted. Stops come
     * unordered from @Relation; sort by seq_order.
     */
    @Transaction
    @Query("SELECT * FROM driver_route LIMIT 1")
    fun observeRouteWithStops(): Flow<RouteWithStops?>

    @Query("SELECT * FROM driver_route LIMIT 1")
    fun observeRoute(): Flow<RouteEntity?>

    @Query("SELECT * FROM route_stop WHERE route_id = :routeId ORDER BY seq_order")
    fun observeStops(routeId: String): Flow<List<RouteStopEntity>>

    /**
     * Stores a newly assigned route. Whatever route was on the device before is
     * removed with its stops (cascade): a replaced route's crew locations do
     * not stay on the driver's phone.
     */
    @Transaction
    suspend fun saveActiveRoute(route: RouteEntity, stops: List<RouteStopEntity>) {
        deleteAllRoutes()
        insertRoute(route)
        insertStops(stops)
    }

    /** Removes a route and its stops, when the server reports it completed or superseded. */
    @Query("DELETE FROM driver_route WHERE id = :routeId")
    suspend fun purgeRoute(routeId: String)

    @Query("DELETE FROM driver_route")
    suspend fun deleteAllRoutes()

    @Insert
    suspend fun insertRoute(route: RouteEntity)

    @Insert
    suspend fun insertStops(stops: List<RouteStopEntity>)
}
