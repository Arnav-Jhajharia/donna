"""Local browser test client for the LiveKit voice agent.

Hits one endpoint to mint a join token, serves one HTML page that
joins the room, publishes mic, subscribes to whatever the agent
publishes back. Bypasses agents-playground entirely.

Also serves a streaming /voice/test-log endpoint that tails the
agent worker log and the donna API log into the page so you can
watch what's happening in real time.

Open http://localhost:8000/voice/test in a browser.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/voice")


_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>donna voice test</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background:#111; color:#eee; padding:32px; max-width:640px; margin:auto; }
    h1 { font-weight:300; letter-spacing:0.05em; }
    button { background:#3a3; color:#fff; border:0; padding:14px 24px; border-radius:6px; font-size:16px; cursor:pointer; }
    button:disabled { background:#333; color:#999; cursor:not-allowed; }
    button.stop { background:#a33; }
    #status { margin:16px 0; padding:12px; background:#1a1a1a; border-radius:4px; font-family: monospace; font-size:13px; }
    #log { margin-top:16px; padding:12px; background:#0a0a0a; border-radius:4px; font-family: monospace; font-size:11px; white-space:pre-wrap; height:200px; overflow-y:auto; }
    #serverlog { margin-top:8px; padding:12px; background:#000; border-radius:4px; font-family: monospace; font-size:10px; white-space:pre-wrap; height:280px; overflow-y:auto; color:#9af; }
    .small { color:#666; font-size:12px; }
    h2 { font-size:14px; color:#888; margin-top:24px; margin-bottom:4px; font-weight:400; }
    .audiometer { display:inline-block; height:8px; background:#333; width:240px; border-radius:4px; overflow:hidden; vertical-align:middle; margin-left:8px; }
    .audiometer .fill { height:100%; background:#3a3; width:0%; transition: width 80ms; }
  </style>
</head>
<body>
  <h1>donna · voice test</h1>
  <p class="small">connects to your livekit project as donna-voice agent. mic only.</p>

  <button id="connect">connect</button>
  <button id="disconnect" class="stop" disabled>disconnect</button>

  <div id="status">idle</div>
  <div>mic level <div class="audiometer"><div class="fill" id="meter"></div></div></div>

  <h2>client log</h2>
  <div id="log"></div>

  <h2>server log (agent + donna api, live)</h2>
  <div id="serverlog"></div>

  <script src="https://cdn.jsdelivr.net/npm/livekit-client/dist/livekit-client.umd.min.js"></script>
  <script>
    const Room = window.LivekitClient.Room;
    const RoomEvent = window.LivekitClient.RoomEvent;
    const Track = window.LivekitClient.Track;

    const $status = document.getElementById('status');
    const $log = document.getElementById('log');
    const $serverlog = document.getElementById('serverlog');
    const $meter = document.getElementById('meter');
    const $connect = document.getElementById('connect');
    const $disconnect = document.getElementById('disconnect');

    let room = null;
    let serverLogReader = null;

    // Live tail of /voice/test-log — server pipes agent + donna api logs.
    function startServerLog() {
      const ev = new EventSource('/voice/test-log');
      ev.onmessage = (m) => {
        const t = new Date().toTimeString().slice(0, 8);
        $serverlog.textContent += `[${t}] ${m.data}\n`;
        $serverlog.scrollTop = $serverlog.scrollHeight;
      };
      ev.onerror = () => { ev.close(); };
      serverLogReader = ev;
    }
    startServerLog();

    function setStatus(s) { $status.textContent = s; }
    function log(line) {
      const t = new Date().toTimeString().slice(0, 8);
      $log.textContent += `[${t}] ${line}\\n`;
      $log.scrollTop = $log.scrollHeight;
    }

    async function connect() {
      $connect.disabled = true;
      setStatus('requesting token...');
      log('requesting join token from /voice/test-token');

      const r = await fetch('/voice/test-token', { method: 'POST' });
      if (!r.ok) {
        const t = await r.text();
        setStatus('token failed: ' + r.status);
        log('error: ' + t);
        $connect.disabled = false;
        return;
      }
      const { url, token, room: roomName } = await r.json();
      log('token ok. room=' + roomName);

      room = new Room({
        adaptiveStream: true,
        dynacast: true,
      });

      room
        .on(RoomEvent.Connected, () => {
          log('connected to room');
          setStatus('connected — speak now');
        })
        .on(RoomEvent.ParticipantConnected, (p) => log('participant: ' + p.identity))
        .on(RoomEvent.TrackSubscribed, (track, pub, p) => {
          log('subscribed: ' + p.identity + ' / ' + track.kind);
          if (track.kind === Track.Kind.Audio) {
            const el = track.attach();
            el.autoplay = true;
            document.body.appendChild(el);
          }
        })
        .on(RoomEvent.Disconnected, () => {
          log('disconnected');
          setStatus('disconnected');
          $connect.disabled = false;
          $disconnect.disabled = true;
        })
        .on(RoomEvent.MediaDevicesError, (e) => log('media error: ' + e.message));

      try {
        await room.connect(url, token);
        await room.localParticipant.setMicrophoneEnabled(true);
        log('mic published');
        $disconnect.disabled = false;

        // Mic level meter via Web Audio API for confirmation that mic is hot.
        try {
          const stream = new MediaStream();
          const trackPub = Array.from(room.localParticipant.audioTrackPublications.values())[0];
          if (trackPub && trackPub.track) {
            stream.addTrack(trackPub.track.mediaStreamTrack);
            const ac = new (window.AudioContext || window.webkitAudioContext)();
            const src = ac.createMediaStreamSource(stream);
            const analyser = ac.createAnalyser();
            analyser.fftSize = 256;
            src.connect(analyser);
            const buf = new Uint8Array(analyser.frequencyBinCount);
            const tick = () => {
              analyser.getByteTimeDomainData(buf);
              let sum = 0;
              for (let i = 0; i < buf.length; i++) {
                const v = (buf[i] - 128) / 128;
                sum += v * v;
              }
              const rms = Math.sqrt(sum / buf.length);
              $meter.style.width = Math.min(100, Math.round(rms * 400)) + '%';
              if (room && room.state === 'connected') requestAnimationFrame(tick);
            };
            tick();
          }
        } catch (e) {
          log('mic meter failed: ' + e.message);
        }
      } catch (e) {
        log('connect failed: ' + e.message);
        setStatus('connect failed');
        $connect.disabled = false;
      }
    }

    async function disconnect() {
      if (room) {
        await room.disconnect();
        room = null;
      }
      $connect.disabled = false;
      $disconnect.disabled = true;
    }

    $connect.addEventListener('click', connect);
    $disconnect.addEventListener('click', disconnect);
  </script>
</body>
</html>
"""


@router.get("/test", response_class=HTMLResponse)
async def test_page() -> HTMLResponse:
    return HTMLResponse(_HTML)


@router.get("/test-log")
async def test_log_stream() -> StreamingResponse:
    """Tail /tmp/agent.log + /tmp/donna_api.log and stream as SSE.
    The HTML page subscribes to this so you can watch what's happening
    in real time without flipping to a separate terminal."""

    paths = [
        ("agent", Path("/tmp/agent.log")),
        ("donna", Path("/tmp/donna_api.log")),
    ]

    # Open files at end-of-file so we only see new lines.
    handles: list[tuple[str, object]] = []
    for label, path in paths:
        try:
            f = open(path, "r", encoding="utf-8", errors="replace")
            f.seek(0, 2)
            handles.append((label, f))
        except FileNotFoundError:
            pass

    async def gen():
        try:
            yield b": connected to test-log stream\n\n"
            while True:
                emitted = False
                for label, f in handles:
                    line = f.readline()
                    while line:
                        emitted = True
                        clean = line.rstrip("\n")
                        # Filter noisy lines.
                        if any(skip in clean for skip in (
                            "DEBUG    asyncio",
                            "Watching /Users",
                            "uploading session report",
                            "finished uploading",
                            "shutting down job task",
                        )):
                            line = f.readline()
                            continue
                        # SSE-encode.
                        msg = f"{label}: {clean[:300]}"
                        msg = msg.replace("\n", " ")
                        yield f"data: {msg}\n\n".encode()
                        line = f.readline()
                if not emitted:
                    await asyncio.sleep(0.3)
        finally:
            for _, f in handles:
                try:
                    f.close()
                except Exception:
                    pass

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/test-token")
async def test_token() -> JSONResponse:
    url = os.environ.get("LIVEKIT_URL")
    key = os.environ.get("LIVEKIT_API_KEY")
    secret = os.environ.get("LIVEKIT_API_SECRET")
    if not url or not key or not secret:
        raise HTTPException(500, "LIVEKIT_URL/API_KEY/API_SECRET not set")

    try:
        from livekit import api  # type: ignore
    except ImportError:
        raise HTTPException(500, "livekit-api not installed")

    room_name = f"donna-test-{uuid.uuid4().hex[:8]}"
    identity = f"user-{uuid.uuid4().hex[:6]}"

    # Token + agent dispatch: tell the room to spawn the donna-agent
    # worker on participant join. The agent_name must match the
    # registered worker (donna-voice/agent.py uses DONNA_AGENT_NAME,
    # default 'donna-agent').
    agent_name = os.environ.get("DONNA_AGENT_NAME", "donna-agent")

    grant = api.VideoGrants(
        room_join=True,
        room=room_name,
        can_publish=True,
        can_subscribe=True,
        can_publish_data=True,
    )
    builder = (
        api.AccessToken(key, secret)
        .with_identity(identity)
        .with_name("test user")
        .with_grants(grant)
    )

    try:
        # livekit-api 1.1+ — RoomConfiguration with explicit agent dispatch.
        room_cfg = api.RoomConfiguration(
            agents=[api.RoomAgentDispatch(agent_name=agent_name)],
        )
        builder = builder.with_room_config(room_cfg)
    except Exception as e:
        logger.warning("voice/test-token: agent dispatch unsupported (%s)", e)

    token = builder.to_jwt()

    return JSONResponse({
        "url": url,
        "token": token,
        "room": room_name,
        "identity": identity,
    })
