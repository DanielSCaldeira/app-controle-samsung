package com.factory.samsungremote.network.discovery

import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.IOException

/**
 * [TvCandidateValidator] backed by OkHttp: issues `GET {scheme}://{host}:{port}/api/v2/`
 * and delegates the body to [SamsungDeviceInfoParser].
 *
 * Samsung TVs expose their device-info document over plain HTTP on port `8001`
 * (the same host that serves the control WebSocket on `8002`), so the defaults
 * target that endpoint. The blocking OkHttp call is moved off the caller's
 * thread onto [ioDispatcher]. Any [IOException] (timeout, connection refused,
 * non-TV host) maps to `null` rather than propagating, per the
 * [TvCandidateValidator] contract.
 *
 * @param client     OkHttp client; configure short connect/read timeouts so the
 *                   `< 5 s` discovery budget is respected even when probing many
 *                   dead candidates.
 * @param port       Device-info port; defaults to Samsung's `8001`.
 * @param scheme     URL scheme; defaults to `http`.
 * @param ioDispatcher Dispatcher the synchronous HTTP call runs on.
 * @param parse      Pure parser hook; overridable in tests, defaults to
 *                   [SamsungDeviceInfoParser.parse].
 */
class RestTvCandidateValidator(
    private val client: OkHttpClient,
    private val port: Int = DEFAULT_API_PORT,
    private val scheme: String = "http",
    private val ioDispatcher: CoroutineDispatcher = Dispatchers.IO,
    private val parse: (json: String, fallbackIp: String) -> DiscoveredTv? =
        SamsungDeviceInfoParser::parse,
) : TvCandidateValidator {

    override suspend fun validate(host: String): DiscoveredTv? = withContext(ioDispatcher) {
        val url = "$scheme://$host:$port/api/v2/"
        val request = Request.Builder().url(url).get().build()
        try {
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) return@use null
                val body = response.body?.string() ?: return@use null
                parse(body, host)
            }
        } catch (_: IOException) {
            null
        }
    }

    companion object {
        /** Default HTTP port of the Samsung TV device-info / REST API. */
        const val DEFAULT_API_PORT: Int = 8001
    }
}
