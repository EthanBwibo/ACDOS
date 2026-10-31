package com.kq.acdos.data.remote

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass
import com.squareup.moshi.JsonDataException
import com.squareup.moshi.JsonEncodingException
import java.io.IOException
import okhttp3.ResponseBody
import retrofit2.Response

/**
 * The backend's error codes (ErrorCode in docs/openapi.json). Callers
 * switch on these, never on the HTTP status or the detail text.
 */
enum class ErrorCode {
    @Json(name = "unauthorized")
    UNAUTHORIZED,

    @Json(name = "forbidden")
    FORBIDDEN,

    @Json(name = "not_found")
    NOT_FOUND,

    @Json(name = "method_not_allowed")
    METHOD_NOT_ALLOWED,

    @Json(name = "unavailable")
    UNAVAILABLE,

    @Json(name = "validation_failed")
    VALIDATION_FAILED,

    @Json(name = "idempotency_key_reused")
    IDEMPOTENCY_KEY_REUSED,

    @Json(name = "duplicate_ids")
    DUPLICATE_IDS,

    @Json(name = "unknown_ids")
    UNKNOWN_IDS,

    @Json(name = "not_plannable")
    NOT_PLANNABLE,

    @Json(name = "departed_routes")
    DEPARTED_ROUTES,

    @Json(name = "left_behind_on_route")
    LEFT_BEHIND_ON_ROUTE,

    @Json(name = "payload_too_large")
    PAYLOAD_TOO_LARGE,

    @Json(name = "driver_mismatch")
    DRIVER_MISMATCH,

    @Json(name = "not_your_stop")
    NOT_YOUR_STOP,

    @Json(name = "already_confirmed")
    ALREADY_CONFIRMED,

    /**
     * The generic error: a code newer than this app, or a body that isn't an
     * ErrorBody at all (a proxy's HTML 502, an empty body). Not in the contract.
     */
    UNKNOWN
}

/** Every 4xx and 5xx from the backend carries this body (#126). */
@JsonClass(generateAdapter = true)
data class ErrorBodyDto(
    val code: ErrorCode,
    /** For people and logs; never parsed. */
    val detail: String,
    /** Only present when the error is about these ids. */
    @Json(name = "pickup_request_ids") val pickupRequestIds: List<String> = emptyList(),
    @Json(name = "vehicle_ids") val vehicleIds: List<String> = emptyList()
)

/** What one API call came back with. */
sealed interface ApiResult<out T> {
    data class Success<T>(val body: T) : ApiResult<T>

    /**
     * The server answered, but not with the body we wanted. Switch on [code].
     * [body] is null when the response wasn't an ErrorBody; [code] is then
     * UNKNOWN. [status] is null only when a 2xx body couldn't be read.
     */
    data class Error(val status: Int?, val body: ErrorBodyDto?) : ApiResult<Nothing> {
        val code: ErrorCode get() = body?.code ?: ErrorCode.UNKNOWN
    }

    /** No answer: offline, a timeout, a dropped connection. */
    data class NetworkError(val cause: IOException) : ApiResult<Nothing>
}

private val errorBodyAdapter = ApiClient.moshi.adapter(ErrorBodyDto::class.java)

/**
 * Runs one call and sorts the outcome. Every caller goes through here, so
 * every non-2xx response is read the same way and nothing the server sends
 * can crash the app.
 */
suspend fun <T : Any> apiCall(call: suspend () -> Response<T>): ApiResult<T> {
    val response = try {
        call()
    } catch (e: JsonDataException) {
        // A 2xx body that doesn't match its DTO. OpenApiContractTest is meant
        // to catch this in CI; on a phone it is the generic error.
        return ApiResult.Error(status = null, body = null)
    } catch (e: JsonEncodingException) {
        // 2xx with malformed JSON. An IOException subclass, so caught before
        // the next clause: it is a bad answer, not a missing one. A body cut
        // off mid-way is a plain EOFException, so it stays a NetworkError.
        return ApiResult.Error(status = null, body = null)
    } catch (e: IOException) {
        return ApiResult.NetworkError(e)
    }
    if (!response.isSuccessful) {
        return ApiResult.Error(response.code(), readErrorBody(response.errorBody()))
    }
    val body = response.body() ?: return ApiResult.Error(response.code(), null)
    return ApiResult.Success(body)
}

/** Null when [raw] isn't a valid ErrorBody: empty, HTML, or another JSON shape. */
internal fun readErrorBody(raw: ResponseBody?): ErrorBodyDto? = try {
    raw?.use { errorBodyAdapter.fromJson(it.source()) }
} catch (e: IOException) {
    null
} catch (e: JsonDataException) {
    null
}
