package com.vive.ui.screens

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.vive.core.ServiceLocator
import com.vive.core.UiState
import com.vive.core.ViveResult
import com.vive.data.model.Alert
import com.vive.data.model.ModelInfo
import com.vive.data.model.Packet
import com.vive.data.model.Session
import com.vive.data.model.TranscriptLine
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * Shared state holders.
 *
 * Four view models cover every data-backed screen, so the app has ONE
 * state-management approach (the `UiState` sealed interface from Phase 1)
 * rather than a second architecture layered on top.
 *
 * Repositories come from [ServiceLocator], which currently serves demo data.
 */

/** Loads a list, mapping an empty result to [UiState.Empty]. */
private fun <T> ViveResult<List<T>>.toListState(): UiState<List<T>> = when (this) {
    is ViveResult.Success -> if (data.isEmpty()) UiState.Empty else UiState.Success(data)
    is ViveResult.Failure -> UiState.Error(error)
}

private fun <T> ViveResult<T>.toState(): UiState<T> = when (this) {
    is ViveResult.Success -> UiState.Success(data)
    is ViveResult.Failure -> UiState.Error(error)
}

/** Home and Call History. */
class SessionListViewModel : ViewModel() {

    private val _state = MutableStateFlow<UiState<List<Session>>>(UiState.Loading)
    val state: StateFlow<UiState<List<Session>>> = _state.asStateFlow()

    init { refresh() }

    fun refresh() = viewModelScope.launch {
        _state.value = UiState.Loading
        _state.value = ServiceLocator.sessions.listSessions().toListState()
    }
}

/**
 * Backs the active-call, summary, risk, evidence, timeline and transcript
 * screens. One view model per session keeps packet history in a single place
 * so the risk graph and the timeline never disagree.
 */
class SessionDetailViewModel(private val sessionId: String) : ViewModel() {

    private val _session = MutableStateFlow<UiState<Session>>(UiState.Loading)
    val session: StateFlow<UiState<Session>> = _session.asStateFlow()

    private val _packets = MutableStateFlow<UiState<List<Packet>>>(UiState.Loading)
    val packets: StateFlow<UiState<List<Packet>>> = _packets.asStateFlow()

    private val _transcript = MutableStateFlow<UiState<List<TranscriptLine>>>(UiState.Loading)
    val transcript: StateFlow<UiState<List<TranscriptLine>>> = _transcript.asStateFlow()

    init { refresh() }

    fun refresh() = viewModelScope.launch {
        _session.value = UiState.Loading
        _packets.value = UiState.Loading
        _transcript.value = UiState.Loading
        _session.value = ServiceLocator.sessions.getSession(sessionId).toState()
        _packets.value = ServiceLocator.sessions.listPackets(sessionId).toListState()
        _transcript.value = ServiceLocator.sessions.getTranscript(sessionId).toListState()
    }

    /** Risk score per packet, in order - the series behind the overall graph. */
    fun riskSeries(): List<Int> =
        (_packets.value as? UiState.Success)?.data?.map { it.risk.score }.orEmpty()

    fun latestPacket(): Packet? =
        (_packets.value as? UiState.Success)?.data?.lastOrNull()
}

/** Single packet detail. */
class PacketDetailViewModel(
    private val sessionId: String,
    private val packetId: String,
) : ViewModel() {

    private val _state = MutableStateFlow<UiState<Packet>>(UiState.Loading)
    val state: StateFlow<UiState<Packet>> = _state.asStateFlow()

    init { refresh() }

    fun refresh() = viewModelScope.launch {
        _state.value = UiState.Loading
        _state.value = ServiceLocator.sessions.getPacket(sessionId, packetId).toState()
    }
}

/** Alerts list, with acknowledgement. */
class AlertsViewModel : ViewModel() {

    private val _state = MutableStateFlow<UiState<List<Alert>>>(UiState.Loading)
    val state: StateFlow<UiState<List<Alert>>> = _state.asStateFlow()

    private val _filter = MutableStateFlow<String>("All")
    val filter: StateFlow<String> = _filter.asStateFlow()

    init { refresh() }

    fun refresh() = viewModelScope.launch {
        _state.value = UiState.Loading
        _state.value = ServiceLocator.alerts.listAlerts().toListState()
    }

    fun setFilter(value: String) { _filter.value = value }

    fun acknowledge(alertId: String) = viewModelScope.launch {
        ServiceLocator.alerts.acknowledge(alertId)
        refresh()
    }
}

/** Model Information screen. */
class ModelsViewModel : ViewModel() {

    private val _state = MutableStateFlow<UiState<List<ModelInfo>>>(UiState.Loading)
    val state: StateFlow<UiState<List<ModelInfo>>> = _state.asStateFlow()

    init { refresh() }

    fun refresh() = viewModelScope.launch {
        _state.value = UiState.Loading
        _state.value = ServiceLocator.models.listModels().toListState()
    }
}
