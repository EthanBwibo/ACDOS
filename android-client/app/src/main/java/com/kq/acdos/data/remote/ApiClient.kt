package com.kq.acdos.data.remote

import com.kq.acdos.auth.AccessTokenProvider
import com.squareup.moshi.FromJson
import com.squareup.moshi.Moshi
import com.squareup.moshi.ToJson
import java.time.Instant
import java.time.OffsetDateTime
import java.util.concurrent.TimeUnit
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory

/**
 * Timestamps from the backend are ISO 8601 and may carry fractional seconds
 * (2026-10-30T06:50:34.037197Z). OffsetDateTime.parse accepts an optional
 * fraction and both "Z" and "+03:00" on every Android version. Instant.parse
 * accepts the fraction too, but offsets other than "Z" only from Java 12 on,
 * which older Android versions (minSdk 26) don't have.
 */
object InstantAdapter {
    @FromJson
    fun fromJson(value: String): Instant = OffsetDateTime.parse(value).toInstant()

    @ToJson
    fun toJson(value: Instant): String = value.toString()
}

/** Builds the Retrofit client for the FastAPI backend. */
object ApiClient {
    val moshi: Moshi = Moshi.Builder().add(InstantAdapter).build()

    fun okHttp(tokens: AccessTokenProvider): OkHttpClient = OkHttpClient.Builder()
        .addInterceptor(BearerTokenInterceptor(tokens))
        .authenticator(TokenAuthenticator(tokens))
        // 2G/3G: OkHttp's 10 s defaults are short for a slow handshake.
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    fun retrofit(baseUrl: String, client: OkHttpClient): Retrofit = Retrofit.Builder()
        // Retrofit needs the trailing slash to resolve relative paths.
        .baseUrl(if (baseUrl.endsWith("/")) baseUrl else "$baseUrl/")
        .client(client)
        .addConverterFactory(MoshiConverterFactory.create(moshi))
        .build()
}
