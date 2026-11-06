package com.kq.acdos.data

import com.kq.acdos.data.local.CrewDao
import com.kq.acdos.data.local.PresetMessageEntity
import com.kq.acdos.data.remote.ApiResult
import com.kq.acdos.data.remote.CrewMessageCreateDto
import com.kq.acdos.data.remote.CrewMessageDto
import com.kq.acdos.data.remote.CrewMessageReadDto
import com.kq.acdos.data.remote.MessageReplyCreateDto
import com.kq.acdos.data.remote.MessageReplyDto
import com.kq.acdos.data.remote.MessagesApi
import com.kq.acdos.data.remote.PresetMessageDto
import com.kq.acdos.data.remote.apiCall

/**
 * Preset messages (#57). The presets are kept in Room so the Message tab
 * still lists them with no signal; sending needs the network.
 */
class MessagesRepository(private val api: MessagesApi, private val dao: CrewDao) {
    /** Replaces the cached presets with the server's. A failure keeps the cache. */
    suspend fun refreshPresets(): ApiResult<Unit> = when (val result = apiCall { api.presets() }) {
        is ApiResult.Success -> {
            // The server's presets have no id; the code is unique, so it is the key.
            dao.replacePresets(
                result.body.items.map { PresetMessageEntity(it.code, it.code, it.label) }
            )
            ApiResult.Success(Unit)
        }

        is ApiResult.Error -> result

        is ApiResult.NetworkError -> result
    }

    /** [idempotencyKey] stays the same across retries of one tap, so it is sent once. */
    suspend fun send(presetCode: String, idempotencyKey: String): ApiResult<CrewMessageDto> =
        apiCall { api.send(idempotencyKey, CrewMessageCreateDto(presetCode)) }

    /** Safe to retry: the first read time stands. */
    suspend fun markRead(messageId: String): ApiResult<CrewMessageReadDto> =
        apiCall { api.markRead(messageId) }

    /**
     * The presets the dispatcher may reply with. The server picks them by
     * caller. Not cached: replying needs the network anyway.
     */
    suspend fun replyPresets(): ApiResult<List<PresetMessageDto>> =
        when (val result = apiCall { api.presets() }) {
            is ApiResult.Success -> ApiResult.Success(result.body.items)
            is ApiResult.Error -> result
            is ApiResult.NetworkError -> result
        }

    /** [idempotencyKey] stays the same across retries of one tap, so it is sent once. */
    suspend fun reply(
        messageId: String,
        presetCode: String,
        idempotencyKey: String
    ): ApiResult<MessageReplyDto> =
        apiCall { api.reply(messageId, idempotencyKey, MessageReplyCreateDto(presetCode)) }

    /** The dispatcher's inbox: the latest page, newest first. */
    suspend fun inbox(): ApiResult<List<CrewMessageDto>> = latest(INBOX_SIZE)

    /** The crew member's own latest messages, newest first. The server filters by caller. */
    suspend fun recent(): ApiResult<List<CrewMessageDto>> = latest(RECENT_SIZE)

    private suspend fun latest(limit: Int): ApiResult<List<CrewMessageDto>> =
        when (val result = apiCall { api.messages(limit = limit) }) {
            is ApiResult.Success -> ApiResult.Success(result.body.items)
            is ApiResult.Error -> result
            is ApiResult.NetworkError -> result
        }

    companion object {
        /** How many messages the crew member's RECENT list shows. */
        const val RECENT_SIZE = 5

        /** The server's largest page; enough for a morning's messages. */
        private const val INBOX_SIZE = 50
    }
}
