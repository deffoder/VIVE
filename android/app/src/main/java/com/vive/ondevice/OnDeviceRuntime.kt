package com.vive.ondevice

import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import android.content.Context
import java.io.File

/**
 * Where on-device models live and how ONNX Runtime sessions are created.
 *
 * Models are NOT inside the APK. Together they are several hundred MB, and a
 * graph inside the APK is compressed and must be extracted before it can be
 * mapped, doubling its footprint on disk. They are provisioned once into the
 * app's own external files directory (`scripts/mobile/provision_device.py`)
 * and read from there. After provisioning nothing leaves the phone and no
 * computer is involved: provisioning is installation, like the APK itself.
 */
object OnDeviceRuntime {

    val env: OrtEnvironment by lazy { OrtEnvironment.getEnvironment() }

    /** `/sdcard/Android/data/com.vive/files/models`, app-private. */
    fun modelDir(context: Context): File =
        File(context.getExternalFilesDir(null), "models")

    /**
     * CPU execution with all big cores. Graph optimisation is left at the
     * default (ALL): the graphs were exported with constant folding already
     * applied, and measured on the device before any other provider is tried.
     */
    fun session(file: File, threads: Int = DEFAULT_THREADS): OrtSession {
        val options = OrtSession.SessionOptions().apply {
            setIntraOpNumThreads(threads)
            setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT)
        }
        return env.createSession(file.absolutePath, options)
    }

    const val DEFAULT_THREADS = 4
}
