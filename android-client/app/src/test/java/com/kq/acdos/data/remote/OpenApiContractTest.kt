package com.kq.acdos.data.remote

import com.squareup.moshi.JsonDataException
import com.squareup.moshi.Types
import java.io.File
import java.lang.reflect.Method
import java.lang.reflect.Modifier
import java.lang.reflect.ParameterizedType
import java.lang.reflect.WildcardType
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST

/**
 * docs/openapi.json is the backend's contract (#126). If the backend renames
 * a field, changes whether it can be null or left out, adds an enum value or
 * moves a path, this fails on our side. Gradle passes the file's path in
 * acdos.openapi.
 *
 * The DTO checks use Moshi itself, the parser the app runs: build a JSON
 * example from the schema, then see what the DTO accepts and writes back.
 */
class OpenApiContractTest {
    private val moshi = ApiClient.moshi

    @Suppress("UNCHECKED_CAST")
    private val spec: Map<String, Any?> = run {
        val path = System.getProperty("acdos.openapi") ?: error("acdos.openapi is not set")
        val type = Types.newParameterizedType(Map::class.java, String::class.java, Any::class.java)
        moshi.adapter<Map<String, Any?>>(type).fromJson(File(path).readText())!!
    }

    private val schemas = spec.obj("components").obj("schemas")

    /** Every object schema the app reads or sends, and its DTO. */
    private val dtos: Map<String, Class<*>> = mapOf(
        "DriverRouteResponse" to DriverRouteResponseDto::class.java,
        "DriverRoute" to DriverRouteDto::class.java,
        "DriverStop" to DriverStopDto::class.java,
        "RouteSummaryPage" to RouteSummaryPageDto::class.java,
        "RouteSummary" to RouteSummaryDto::class.java,
        "CrewPickupResponse" to CrewPickupResponseDto::class.java,
        "CrewPickup" to CrewPickupDto::class.java,
        "ErrorBody" to ErrorBodyDto::class.java,
        "OptimisationJobCreate" to OptimisationJobCreateDto::class.java,
        "OptimisationJobAccepted" to OptimisationJobAcceptedDto::class.java,
        "OptimisationJobResult" to OptimisationJobResultDto::class.java,
        "PlannedRoute" to PlannedRouteDto::class.java,
        "PlannedNode" to PlannedNodeDto::class.java,
        "LatePickup" to LatePickupDto::class.java
    )

    private val enums: Map<String, Class<out Enum<*>>> = mapOf(
        "RouteStatus" to RouteStatusDto::class.java,
        "PickupRequestStatus" to PickupRequestStatusDto::class.java,
        "OptimizationJobStatus" to OptimizationJobStatusDto::class.java,
        "OptimizationTriggerType" to OptimizationTriggerTypeDto::class.java,
        "ErrorCode" to ErrorCode::class.java
    )

    @Test
    fun everyEndpointTheAppCalls_isInTheContractWithTheSameBodies() {
        // Static methods are Kotlin's $default helpers for parameters with defaults.
        val services = listOf(MeApi::class.java, OptimisationJobsApi::class.java)
        val methods = services.flatMap { it.declaredMethods.toList() }
            .filterNot { Modifier.isStatic(it.modifiers) }
        for (method in methods) {
            val (verb, path) = method.httpRoute()
            val operation = spec.obj("paths")[path]?.let { (it as Map<*, *>)[verb] }
            assertNotNull("$verb $path (${method.name}) is not in the contract", operation)
            val responses = (operation as Map<*, *>).obj("responses")
            for ((status, response) in responses) {
                val ref = schemaRef((response as Map<*, *>).obj("content").obj("application/json"))
                if (status.toString().startsWith("2")) {
                    assertEquals("${method.name} $status", dtos[ref], method.responseBodyType())
                } else {
                    assertEquals("${method.name} $status", "ErrorBody", ref)
                }
            }
            method.requestBodyType()?.let { body ->
                val media = operation.obj("requestBody").obj("content").obj("application/json")
                assertEquals("${method.name} request body", dtos[schemaRef(media)], body)
            }
        }
    }

    @Test
    fun dtoFieldNames_matchTheirSchemas() {
        for ((name, dto) in dtos) {
            val example = example(schemas.obj(name))
            val written = roundTrip(dto, example)

            assertEquals(name, (example as Map<*, *>).keys, (written as Map<*, *>).keys)
            assertEquals(name, normalise(example), normalise(written))
        }
    }

    @Test
    fun dtoNullability_andOptionalFields_matchTheirSchemas() {
        val mismatches = mutableListOf<String>()
        for ((name, dto) in dtos) {
            val schema = schemas.obj(name)
            val required = (schema["required"] as List<*>?).orEmpty()

            @Suppress("UNCHECKED_CAST")
            val example = example(schema) as Map<String, Any?>
            for ((field, property) in schema.obj("properties")) {
                val nullable = isNullable(property as Map<*, *>)
                if (accepts(dto, example + (field to null)) != nullable) {
                    val expected = if (nullable) "accept" else "reject"
                    mismatches += "$name.$field: should $expected null"
                }
                val acceptsMissing = accepts(dto, example - field)
                if (field !in required && !acceptsMissing) {
                    mismatches += "$name.$field: optional in the contract, required by the DTO"
                }
                if (field in required && !nullable && acceptsMissing) {
                    mismatches += "$name.$field: required in the contract, has a default in the DTO"
                }
            }
        }
        assertEquals(emptyList<String>(), mismatches)
    }

    @Test
    fun enumValues_matchTheContract() {
        for ((name, type) in enums) {
            val adapter = moshi.adapter<Any>(type)
            val inApp = type.enumConstants!!
                .filter { it != ErrorCode.UNKNOWN }
                .map { adapter.toJsonValue(it) }
                .toSet()

            assertEquals(name, (schemas.obj(name)["enum"] as List<*>).toSet(), inApp)
        }
    }

    private fun Method.httpRoute(): Pair<String, String> {
        getAnnotation(GET::class.java)?.let { return "get" to "/" + it.value }
        getAnnotation(POST::class.java)?.let { return "post" to "/" + it.value }
        error("$name has no HTTP annotation this test knows")
    }

    /** T in a suspend fun returning Response<T>: Kotlin passes it as Continuation<Response<T>>. */
    private fun Method.responseBodyType(): Class<*> {
        val continuation = genericParameterTypes.last() as ParameterizedType
        val response = (continuation.actualTypeArguments[0] as WildcardType).lowerBounds[0]
        return (response as ParameterizedType).actualTypeArguments[0] as Class<*>
    }

    /** The type of the @Body parameter, or null for a call without a body. */
    private fun Method.requestBodyType(): Class<*>? {
        val index = parameterAnnotations.indexOfFirst { list -> list.any { it is Body } }
        return if (index >= 0) parameterTypes[index] else null
    }

    /** The schema name a media type object points at. */
    private fun schemaRef(media: Map<*, *>): String = refName(media.obj("schema"))

    private fun refName(schema: Map<*, *>) =
        (schema["\$ref"] as String).removePrefix("#/components/schemas/")

    /** A value for [schema] with every property present and nothing null. */
    private fun example(schema: Map<*, *>): Any? {
        if ("\$ref" in schema) return example(schemas.obj(refName(schema)))
        schema["anyOf"]?.let { branches ->
            val notNull = (branches as List<*>).first { (it as Map<*, *>)["type"] != "null" }
            return example(notNull as Map<*, *>)
        }
        schema["enum"]?.let { return (it as List<*>).first() }
        return when (schema["type"]) {
            "object" -> schema.obj("properties").mapValues { example(it.value as Map<*, *>) }

            "array" -> listOf(example(schema.obj("items")))

            "integer" -> 3

            "number" -> 1.5

            "string" -> when (schema["format"]) {
                "uuid" -> "6f1c2a9e-0d4b-4c57-9a3e-2b8f7d1e5a40"
                "date-time" -> "2026-10-30T03:50:34.037197Z"
                else -> "text"
            }

            else -> error("no example for schema $schema")
        }
    }

    private fun isNullable(property: Map<*, *>) =
        (property["anyOf"] as List<*>?)?.any { (it as Map<*, *>)["type"] == "null" } == true

    private fun accepts(dto: Class<*>, json: Map<String, Any?>): Boolean = try {
        moshi.adapter<Any>(dto).fromJsonValue(json)
        true
    } catch (e: JsonDataException) {
        false
    }

    /** Reads [json] into the DTO and writes it back, nulls included. */
    private fun roundTrip(dto: Class<*>, json: Any?): Any? {
        val adapter = moshi.adapter<Any>(dto)
        return adapter.serializeNulls().toJsonValue(adapter.fromJsonValue(json))
    }

    /** Numbers as Double, so 3 and 3.0 compare equal. */
    private fun normalise(value: Any?): Any? = when (value) {
        is Map<*, *> -> value.mapValues { normalise(it.value) }
        is List<*> -> value.map(::normalise)
        is Number -> value.toDouble()
        else -> value
    }

    @Suppress("UNCHECKED_CAST")
    private fun Map<*, *>.obj(key: String) = this[key] as Map<String, Any?>
}
