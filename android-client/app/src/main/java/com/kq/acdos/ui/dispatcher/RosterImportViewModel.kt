package com.kq.acdos.ui.dispatcher

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.kq.acdos.AcdosApplication
import com.kq.acdos.R
import com.kq.acdos.data.DispatchRepository
import com.kq.acdos.data.remote.ApiResult
import com.kq.acdos.data.remote.RosterImportResultDto
import java.util.UUID
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** The server's limit (docs/roster_import.md), so a bigger file is refused before it's sent. */
const val ROSTER_MAX_BYTES = 256 * 1024

data class RosterImportState(
    /** Null until a file is chosen. */
    val fileName: String? = null,
    /** The dry run: what importing would do. */
    val check: RosterImportResultDto? = null,
    /** What the import did. */
    val imported: RosterImportResultDto? = null,
    /** A call is out. */
    val busy: Boolean = false,
    /** Why the last step failed. */
    val failure: DispatcherMessage? = null,
    /**
     * The request failed, not the file: no connection, a timeout or a 5xx. Only then can
     * Retry help; a problem with the file itself needs another file.
     */
    val retryable: Boolean = false
) {
    /** Retry: after a failed request, never after a refused file. */
    val showRetry: Boolean get() = failure != null && retryable && !busy

    /** "Choose another file" leads when the file itself was the problem. */
    val fileRefused: Boolean get() = failure != null && !retryable && !busy

    /** "Import N pickups": after a dry run that found something to import. */
    val canImport: Boolean
        get() = check != null && imported == null && check.pickupsCreated > 0 && !busy
}

/**
 * Importing a roster CSV (#229): a dry run first, so the dispatcher sees the counts and the
 * rejected rows, then the import on "Import N pickups". [repository] is null in builds without
 * an API URL.
 *
 * Each chosen file gets one Idempotency-Key, kept until another file is chosen. Retrying an
 * import that failed on a weak connection sends the same key, so if the first attempt did
 * reach the server the retry gets its result instead of importing the roster twice.
 */
class RosterImportViewModel(
    private val repository: DispatchRepository?,
    private val newKey: () -> String = { UUID.randomUUID().toString() }
) : ViewModel() {
    private val uiState = MutableStateFlow(RosterImportState())
    val state: StateFlow<RosterImportState> = uiState.asStateFlow()

    private var csv = ByteArray(0)
    private var key = ""

    /** A new file: a fresh key, then the dry run. */
    fun choose(fileName: String, content: ByteArray) {
        csv = content
        key = newKey()
        uiState.value = RosterImportState(fileName = fileName)
        if (content.size > ROSTER_MAX_BYTES) {
            uiState.update { it.copy(failure = DispatcherMessage(R.string.roster_too_large)) }
            return
        }
        check()
    }

    /** Retry after a failed request: the step that failed, with the same key. */
    fun retry() {
        val state = uiState.value
        if (state.fileName == null || !state.showRetry) return
        if (state.check == null) check() else importNow()
    }

    fun importNow() {
        if (!uiState.value.canImport) return
        call(idempotencyKey = key) { result -> copy(imported = result) }
    }

    private fun check() = call(idempotencyKey = null) { result -> copy(check = result) }

    private fun call(
        idempotencyKey: String?,
        done: RosterImportState.(RosterImportResultDto) -> RosterImportState
    ) {
        val repository = repository ?: return
        val name = uiState.value.fileName ?: return
        // Each file has its own key, so it also tells which file a reply is for.
        val file = key
        uiState.update { it.copy(busy = true, failure = null, retryable = false) }
        viewModelScope.launch {
            val result = repository.importRoster(csv, name, idempotencyKey)
            uiState.update { state ->
                // Another file may have been chosen while this one was out.
                if (key != file) return@update state
                when (result) {
                    is ApiResult.Success -> state.done(result.body).copy(busy = false)

                    is ApiResult.Error, is ApiResult.NetworkError -> state.copy(
                        busy = false,
                        failure = failureMessage(result),
                        retryable = isRequestFailure(result)
                    )
                }
            }
        }
    }

    /**
     * True when the request failed rather than the file: no answer, a 408 timeout or a 5xx.
     * A 4xx (wrong columns, too many rows, not allowed) or an unreadable answer would fail
     * the same way again, so it isn't one.
     */
    private fun isRequestFailure(result: ApiResult<Nothing>) = when (result) {
        is ApiResult.NetworkError -> true
        is ApiResult.Error -> result.status.let { it == 408 || (it != null && it >= 500) }
        is ApiResult.Success -> false
    }

    /** Back to nothing chosen, e.g. when the screen is closed after an import. */
    fun clear() {
        csv = ByteArray(0)
        key = ""
        uiState.value = RosterImportState()
    }

    companion object {
        val Factory: ViewModelProvider.Factory = viewModelFactory {
            initializer {
                val app = this[ViewModelProvider.AndroidViewModelFactory.APPLICATION_KEY]
                RosterImportViewModel((app as AcdosApplication).container.dispatchRepository)
            }
        }
    }
}
