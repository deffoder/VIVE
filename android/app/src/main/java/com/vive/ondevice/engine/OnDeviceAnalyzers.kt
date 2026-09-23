package com.vive.ondevice.engine

import com.vive.data.model.AnalyzerStatus
import com.vive.data.model.Behavior
import com.vive.data.model.Intent
import com.vive.ondevice.OnDeviceAntiSpoof
import com.vive.ondevice.OnDeviceAsr
import com.vive.ondevice.OnDeviceSpeaker
import com.vive.ondevice.OnDeviceText
import com.vive.ondevice.OnDeviceVad
import java.io.File

/**
 * The real on-device model stack behind [Analyzers]: Silero VAD, wav2vec2
 * anti-spoofing, ECAPA-TDNN, per-language wav2vec2 CTC ASR and the two
 * DistilBERT heads, all ONNX Runtime on the phone's CPU.
 *
 * Each model loads on first use and stays resident. A model that is missing
 * or fails to load reports LOAD_ERROR on every packet rather than a value.
 */
class OnDeviceAnalyzers(modelDir: File) : Analyzers {

    val vadModel = OnDeviceVad(modelDir)
    val asrModel = OnDeviceAsr(modelDir)
    val speakerModel = OnDeviceSpeaker(modelDir)
    val spoofModel = OnDeviceAntiSpoof(modelDir)
    val textModel = OnDeviceText(modelDir, Intent.entries.map { it.name }, Behavior.entries.map { it.name })

    override val vadVersion: String? get() = vadModel.version

    override fun vad(samples: FloatArray): VadOut {
        val r = vadModel.analyze(samples)
        return VadOut(if (r.available) AnalyzerStatus.AVAILABLE else AnalyzerStatus.LOAD_ERROR,
            r.hasSpeech, r.quality, r.inferenceMs)
    }

    override fun antispoof(samples: FloatArray): ScoreOut {
        val r = spoofModel.score(samples)
        val version = spoofModel.spec?.version
        return when (r.state) {
            OnDeviceAntiSpoof.State.AVAILABLE -> ScoreOut(AnalyzerStatus.AVAILABLE, r.score, version, r.ms)
            // Deliberately not run: known model, not validated on handset audio.
            OnDeviceAntiSpoof.State.NOT_VALIDATED -> ScoreOut(AnalyzerStatus.UNAVAILABLE, null, "$version (not validated)")
            OnDeviceAntiSpoof.State.INSUFFICIENT_AUDIO -> ScoreOut(AnalyzerStatus.INSUFFICIENT_AUDIO, null, version)
            OnDeviceAntiSpoof.State.INFERENCE_ERROR -> ScoreOut(AnalyzerStatus.INFERENCE_ERROR, null, version)
            OnDeviceAntiSpoof.State.UNAVAILABLE -> ScoreOut(AnalyzerStatus.LOAD_ERROR, null, version)
        }
    }

    override fun speaker(samples: FloatArray, reference: FloatArray?): ScoreOut {
        val r = speakerModel.compare(samples, reference)
        val v = speakerModel.version
        return when (r.state) {
            OnDeviceSpeaker.State.MATCH, OnDeviceSpeaker.State.MISMATCH ->
                ScoreOut(AnalyzerStatus.AVAILABLE, r.similarity, v, r.inferenceMs)
            OnDeviceSpeaker.State.NO_REFERENCE -> ScoreOut(AnalyzerStatus.NO_REFERENCE, null, v)
            OnDeviceSpeaker.State.INSUFFICIENT_AUDIO -> ScoreOut(AnalyzerStatus.INSUFFICIENT_AUDIO, null, v)
            OnDeviceSpeaker.State.ENROLLED, OnDeviceSpeaker.State.UNAVAILABLE ->
                ScoreOut(AnalyzerStatus.LOAD_ERROR, null, v)
        }
    }

    override fun asr(samples: FloatArray, language: String): AsrOut {
        val r = asrModel.transcribe(samples, language)
        val status = when (r.status) {
            OnDeviceAsr.Status.AVAILABLE -> AnalyzerStatus.AVAILABLE
            OnDeviceAsr.Status.INSUFFICIENT_AUDIO -> AnalyzerStatus.INSUFFICIENT_AUDIO
            OnDeviceAsr.Status.UNSUPPORTED_LANGUAGE -> AnalyzerStatus.UNSUPPORTED_LANGUAGE
            OnDeviceAsr.Status.LOAD_ERROR -> AnalyzerStatus.LOAD_ERROR
            OnDeviceAsr.Status.INFERENCE_ERROR -> AnalyzerStatus.INFERENCE_ERROR
        }
        return AsrOut(status, r.text, r.confidence, r.modelVersion, r.inferenceMs)
    }

    override fun intent(text: String?, language: String): IntentOut {
        val r = textModel.intent(text, language)
        return IntentOut(r.status.toAnalyzer(), Intent.valueOf(r.label), r.confidence, r.version, r.inferenceMs)
    }

    override fun behavior(text: String?, language: String): BehaviorOut {
        val r = textModel.behavior(text, language)
        return BehaviorOut(r.status.toAnalyzer(), r.labels.map { Behavior.valueOf(it) }, r.confidence, r.version, r.inferenceMs)
    }

    private fun OnDeviceText.Status.toAnalyzer() = when (this) {
        OnDeviceText.Status.AVAILABLE -> AnalyzerStatus.AVAILABLE
        OnDeviceText.Status.INSUFFICIENT_AUDIO -> AnalyzerStatus.INSUFFICIENT_AUDIO
        OnDeviceText.Status.UNSUPPORTED_LANGUAGE -> AnalyzerStatus.UNSUPPORTED_LANGUAGE
        OnDeviceText.Status.LOAD_ERROR -> AnalyzerStatus.LOAD_ERROR
        OnDeviceText.Status.INFERENCE_ERROR -> AnalyzerStatus.INFERENCE_ERROR
    }

    /**
     * Loading costs ~3 s on the phone (text heads 2.2 s). Done lazily on the
     * first window, it stalled the queue and the opening seconds of the call
     * were dropped - measured on the phone. Warm-up runs when the session is
     * created instead, before the microphone starts.
     */
    override fun warmUp(language: String) {
        vadModel.load()
        asrModel.load(language)
        textModel.load()
        speakerModel.load()
        spoofModel.load()
    }

    fun close() {
        asrModel.close()
        textModel.close()
    }
}
