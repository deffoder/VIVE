package com.vive.ui.screens.home

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.vive.core.UiState
import com.vive.core.ViveResult
import com.vive.data.model.Session
import com.vive.data.repository.SessionRepository
import com.vive.data.repository.StubSessionRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * Home dashboard state holder.
 *
 * Exposes a single immutable UiState (docs/ARCHITECTURE.md 6). The repository
 * is constructor-injected with a stub default so Phase 1 needs no DI framework -
 * an unnecessary dependency at this stage.
 */
class HomeViewModel(
    private val sessions: SessionRepository = StubSessionRepository(),
) : ViewModel() {

    private val _state = MutableStateFlow<UiState<List<Session>>>(UiState.Loading)
    val state: StateFlow<UiState<List<Session>>> = _state.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _state.value = UiState.Loading
            _state.value = when (val result = sessions.listSessions()) {
                is ViveResult.Success ->
                    if (result.data.isEmpty()) UiState.Empty
                    else UiState.Success(result.data)
                is ViveResult.Failure -> UiState.Error(result.error)
            }
        }
    }
}
