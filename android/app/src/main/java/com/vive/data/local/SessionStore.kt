package com.vive.data.local

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import com.vive.data.remote.dto.AlertDto
import com.vive.data.remote.dto.PacketDto
import com.vive.data.remote.dto.SessionDto
import com.vive.data.remote.dto.TranscriptLineDto
import kotlinx.serialization.KSerializer
import kotlinx.serialization.json.Json

/**
 * Durable on-device record of sessions, packets, transcript and alerts.
 *
 * Rows hold the same DTO JSON the backend serves, so a stored session reads
 * back through the same mappers as a live one and the two cannot drift.
 *
 * What is NOT stored, deliberately (docs/SECURITY_SPEC.md 4): audio, and the
 * speaker-enrolment embedding. Audio never leaves the analysis window it
 * belongs to. The voiceprint lives only in memory for the session that
 * enrolled it; a voiceprint on disk is a biometric at rest with no purpose
 * the live session does not already serve.
 *
 * The transcript IS stored: the session review screens exist to show it. It
 * sits in app-private storage (`allowBackup=false`), and deleting a session
 * deletes it.
 */
class SessionStore(context: Context) : SQLiteOpenHelper(context, NAME, null, VERSION) {

    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = true }

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE sessions (id TEXT PRIMARY KEY, started_at TEXT, body TEXT NOT NULL)")
        db.execSQL(
            "CREATE TABLE packets (session_id TEXT NOT NULL, seq INTEGER NOT NULL, packet_id TEXT NOT NULL, " +
                "body TEXT NOT NULL, PRIMARY KEY (session_id, seq))",
        )
        db.execSQL(
            "CREATE TABLE transcript (session_id TEXT NOT NULL, seq INTEGER NOT NULL, body TEXT NOT NULL, " +
                "PRIMARY KEY (session_id, seq))",
        )
        db.execSQL(
            "CREATE TABLE alerts (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, raised_at TEXT, " +
                "acknowledged INTEGER NOT NULL DEFAULT 0, body TEXT NOT NULL)",
        )
        db.execSQL("CREATE TABLE counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        // Version 1 is the first schema; nothing to migrate yet.
    }

    // ------------------------------------------------------------ sessions

    fun upsertSession(s: SessionDto) {
        writableDatabase.insertWithOnConflict(
            "sessions", null,
            ContentValues().apply {
                put("id", s.sessionId); put("started_at", s.startedAt); put("body", enc(SessionDto.serializer(), s))
            },
            SQLiteDatabase.CONFLICT_REPLACE,
        )
    }

    fun session(id: String): SessionDto? =
        one("SELECT body FROM sessions WHERE id = ?", arrayOf(id), SessionDto.serializer())

    fun sessions(limit: Int): List<SessionDto> =
        many("SELECT body FROM sessions ORDER BY started_at DESC, id DESC LIMIT $limit", emptyArray(), SessionDto.serializer())

    /** Sessions left STREAMING by a process that died mid-call. */
    fun unfinishedSessions(): List<SessionDto> =
        many("SELECT body FROM sessions", emptyArray(), SessionDto.serializer()).filter { it.status != "ENDED" }

    // ------------------------------------------------------------ packets / transcript

    /**
     * Appends one window's results atomically: a packet, the session snapshot
     * it produced, and its transcript line and alert when there are any. A
     * crash can lose the window in flight, never half of it.
     */
    fun appendWindow(packet: PacketDto, session: SessionDto, line: TranscriptLineDto?, alert: AlertDto?) {
        val db = writableDatabase
        db.beginTransaction()
        try {
            db.insertWithOnConflict("packets", null, ContentValues().apply {
                put("session_id", session.sessionId); put("seq", packet.seq); put("packet_id", packet.packetId)
                put("body", enc(PacketDto.serializer(), packet))
            }, SQLiteDatabase.CONFLICT_REPLACE)
            if (line != null) {
                db.insertWithOnConflict("transcript", null, ContentValues().apply {
                    put("session_id", session.sessionId); put("seq", packet.seq)
                    put("body", enc(TranscriptLineDto.serializer(), line))
                }, SQLiteDatabase.CONFLICT_REPLACE)
            }
            if (alert != null) insertAlert(db, alert)
            upsertSession(session)
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    fun packets(sessionId: String, sinceSeq: Int?): List<PacketDto> = many(
        "SELECT body FROM packets WHERE session_id = ? AND seq > ? ORDER BY seq",
        arrayOf(sessionId, (sinceSeq ?: 0).toString()), PacketDto.serializer(),
    )

    fun packet(sessionId: String, packetId: String): PacketDto? = one(
        "SELECT body FROM packets WHERE session_id = ? AND packet_id = ?", arrayOf(sessionId, packetId),
        PacketDto.serializer(),
    )

    fun transcript(sessionId: String): List<TranscriptLineDto> = many(
        "SELECT body FROM transcript WHERE session_id = ? ORDER BY seq", arrayOf(sessionId),
        TranscriptLineDto.serializer(),
    )

    // ------------------------------------------------------------ alerts

    private fun insertAlert(db: SQLiteDatabase, a: AlertDto) {
        db.insertWithOnConflict("alerts", null, ContentValues().apply {
            put("id", a.alertId); put("session_id", a.sessionId); put("raised_at", a.raisedAt)
            put("acknowledged", if (a.acknowledged) 1 else 0); put("body", enc(AlertDto.serializer(), a))
        }, SQLiteDatabase.CONFLICT_REPLACE)
    }

    fun alerts(sessionId: String?): List<AlertDto> = if (sessionId == null) {
        many("SELECT body FROM alerts ORDER BY raised_at DESC, id DESC", emptyArray(), AlertDto.serializer())
    } else {
        many("SELECT body FROM alerts WHERE session_id = ? ORDER BY raised_at DESC, id DESC", arrayOf(sessionId),
            AlertDto.serializer())
    }

    fun acknowledge(alertId: String): AlertDto? {
        val a = one("SELECT body FROM alerts WHERE id = ?", arrayOf(alertId), AlertDto.serializer()) ?: return null
        val acked = a.copy(acknowledged = true)
        insertAlert(writableDatabase, acked)
        return acked
    }

    /** Monotonic counter that survives restarts, for session and alert ids. */
    @Synchronized
    fun next(counter: String): Long {
        val db = writableDatabase
        db.beginTransaction()
        try {
            val current = db.rawQuery("SELECT value FROM counters WHERE name = ?", arrayOf(counter)).use {
                if (it.moveToFirst()) it.getLong(0) else 0L
            }
            db.insertWithOnConflict("counters", null, ContentValues().apply {
                put("name", counter); put("value", current + 1)
            }, SQLiteDatabase.CONFLICT_REPLACE)
            db.setTransactionSuccessful()
            return current + 1
        } finally {
            db.endTransaction()
        }
    }

    // ------------------------------------------------------------ helpers

    private fun <T> enc(s: KSerializer<T>, v: T) = json.encodeToString(s, v)

    private fun <T> one(sql: String, args: Array<String>, s: KSerializer<T>): T? =
        readableDatabase.rawQuery(sql, args).use { c -> if (c.moveToFirst()) json.decodeFromString(s, c.getString(0)) else null }

    private fun <T> many(sql: String, args: Array<String>, s: KSerializer<T>): List<T> =
        readableDatabase.rawQuery(sql, args).use { c ->
            buildList { while (c.moveToNext()) add(json.decodeFromString(s, c.getString(0))) }
        }

    companion object {
        const val NAME = "vive_sessions.db"
        const val VERSION = 1
    }
}
