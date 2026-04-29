import { useState, useRef, useEffect, useCallback } from 'react';
import { getWsBase } from '../utils/wsBase';
import '../styles/camera.css';

export default function CameraPage() {
  const [statusText, setStatusText]   = useState('Disconnected');
  const [statusType, setStatusType]   = useState('');          // '' | 'ok' | 'err'
  const [terrainText, setTerrainText] = useState('Not calibrated');
  const [terrainOk, setTerrainOk]     = useState(false);
  const [previewMode, setPreviewMode] = useState('empty');     // 'empty' | 'active'
  const [showStop, setShowStop]       = useState(false);
  const [startDisabled, setStartDisabled] = useState(false);

  const wsRef              = useRef(null);
  const streamRef          = useRef(null);
  const videoRef           = useRef(null);
  const canvasRef          = useRef(null);
  const pCtxRef            = useRef(null);
  const runningRef         = useRef(false);
  const calibratedRef      = useRef(false);
  const trackingLoopRef    = useRef(null);
  const startInProgressRef = useRef(false);

  useEffect(() => {
    if (canvasRef.current) pCtxRef.current = canvasRef.current.getContext('2d');
  }, []);

  const setStatus  = useCallback((msg, type = '') => { setStatusText(msg); setStatusType(type); }, []);
  const setTerrain = useCallback((text, ok = false) => { setTerrainText(text); setTerrainOk(ok); }, []);

  const showPreview = useCallback((corners) => {
    const video = videoRef.current, canvas = canvasRef.current, pCtx = pCtxRef.current;
    if (!video || !canvas || !pCtx) return;
    canvas.width  = video.videoWidth;
    canvas.height = video.videoHeight;
    pCtx.drawImage(video, 0, 0, canvas.width, canvas.height);
    if (!corners) { setPreviewMode('empty'); return; }
    const [tl, tr, br, bl] = corners;
    pCtx.beginPath();
    pCtx.moveTo(tl[0], tl[1]);
    pCtx.lineTo(tr[0], tr[1]);
    pCtx.lineTo(br[0], br[1]);
    pCtx.lineTo(bl[0], bl[1]);
    pCtx.closePath();
    pCtx.strokeStyle = '#083879';
    pCtx.lineWidth   = 4;
    pCtx.stroke();
    setPreviewMode('active');
  }, []);

  const capturePreview = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return '';
    const c = document.createElement('canvas');
    c.width = canvas.width; c.height = canvas.height;
    c.getContext('2d').drawImage(canvas, 0, 0, c.width, c.height);
    return c.toDataURL('image/jpeg', 0.7);
  }, []);

  const captureFrame = useCallback(() => {
    const v = videoRef.current;
    if (!v) return '';
    const c = document.createElement('canvas');
    c.width = v.videoWidth; c.height = v.videoHeight;
    c.getContext('2d').drawImage(v, 0, 0, c.width, c.height);
    return c.toDataURL('image/jpeg', 0.7);
  }, []);

  const captureSmall = useCallback(() => {
    const v = videoRef.current;
    if (!v) return '';
    const c = document.createElement('canvas');
    c.width = Math.round(v.videoWidth / 2); c.height = Math.round(v.videoHeight / 2);
    c.getContext('2d').drawImage(v, 0, 0, c.width, c.height);
    return c.toDataURL('image/jpeg', 0.4);
  }, []);

  const calibrate = useCallback(() => {
    const v = videoRef.current, ws = wsRef.current;
    if (!v || !ws) return;
    setTerrain('Detecting...');
    ws.send(JSON.stringify({
      type: 'calibration_frame', image: captureFrame(),
      frame_width: v.videoWidth, frame_height: v.videoHeight,
    }));
  }, [captureFrame, setTerrain]);

  const startTracking = useCallback(() => {
    if (trackingLoopRef.current !== null) return;
    const v = videoRef.current;
    function loop() {
      if (!runningRef.current || !calibratedRef.current) { trackingLoopRef.current = null; return; }
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
          type: 'frame', image: captureSmall(), ts: Date.now(),
          frame_width: v?.videoWidth, frame_height: v?.videoHeight,
        }));
      }
      trackingLoopRef.current = setTimeout(() => requestAnimationFrame(loop), 50); // 20 fps
    }
    requestAnimationFrame(loop);
  }, [captureSmall]);

  const stop = useCallback(() => {
    runningRef.current = calibratedRef.current = false;
    startInProgressRef.current = false;
    if (trackingLoopRef.current !== null) { clearTimeout(trackingLoopRef.current); trackingLoopRef.current = null; }
    showPreview(null);
    streamRef.current?.getTracks().forEach(t => t.stop());
    streamRef.current = null;
    wsRef.current?.close();
    wsRef.current = null;
    setStartDisabled(false);
    setShowStop(false);
    setStatus('Disconnected');
    setTerrain('Not calibrated');
  }, [showPreview, setStatus, setTerrain]);

  const start = useCallback(async () => {
    if (runningRef.current || startInProgressRef.current) return;
    startInProgressRef.current = true;
    setStartDisabled(true);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      });
      streamRef.current = stream;
      const v = videoRef.current;
      if (v) v.srcObject = stream;

      const wsUrl = `${getWsBase()}/camera`;
      function setupSocket() {
        let opened = false;
        // nav automatically sends handshake request to wsUrl
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        // onopen triggered when 101 OK UPGRADE received (ws connection established)
        ws.onopen = () => { opened = true; setStatus('Connected', 'ok'); setTerrain('Waiting for calibration...'); };
        ws.onclose = () => {
          if (!opened) {
            runningRef.current = false;
            setStatus('Connection refused (auth or camera not validated)', 'err');
            setStartDisabled(false); setShowStop(false);
            return;
          }
          setStatus('Reconnecting...');
          if (runningRef.current) setTimeout(setupSocket, 2000);
        };
        ws.onmessage = (e) => {
          const d = JSON.parse(e.data);
          if (d.type === 'start_calibration') calibrate();
          else if (d.type === 'calibration_preview') {
            showPreview(d.corners);
            ws.send(JSON.stringify({
              type: 'calibration_preview', image: capturePreview(),
              corners: d.corners, frame_width: v?.videoWidth, frame_height: v?.videoHeight,
            }));
            setTerrain('Vérifie le contour...');
          }
          else if (d.type === 'calibration_failed') { setTerrain('Not detected ❌'); showPreview(null); }
          else if (d.type === 'calibration_ok') {
            calibratedRef.current = true; showPreview(null);
            setTerrain('Calibrated', true); startTracking();
          }
        };
      }
      setupSocket();
      runningRef.current = true;
      setShowStop(true);
    } catch (err) {
      setStatus('Error: ' + err.message, 'err');
      setStartDisabled(false);
    } finally {
      startInProgressRef.current = false;
    }
  }, [calibrate, capturePreview, setStatus, setTerrain, showPreview, startTracking]);

  useEffect(() => {
    window.addEventListener('beforeunload', stop); // ensures camera and ws are properly closed when leaving page
    return () => window.removeEventListener('beforeunload', stop);
  }, [stop]);

  const pillLabel = statusType === 'ok' ? 'Active' : statusType === 'err' ? 'Error' : 'Inactive';

  return (
    <>
      <header>
        <div className="logo">KickAnalytics</div>
        <a href="/" className="back-link">← Back</a>
      </header>

      <div className="page-content">
        <div className="cam-layout">

          <div className="controls-col">
            <div className="status-card">
              <div className="status-left">
                <div className="lbl">Connection</div>
                <div className="val">{statusText}</div>
              </div>
              <span className={`status-pill${statusType ? ' ' + statusType : ''}`}>
                <span className="status-dot"></span>{pillLabel}
              </span>
            </div>

            <div className="terrain-card">
              <span className="terrain-lbl">Field</span>
              <span className={`terrain-val${terrainOk ? ' ok' : ''}`}>{terrainText}</span>
            </div>

            <div>
              <div className="section-title">Camera control</div>
              <div className="btn-row">
                {!showStop && <button className="btn-red" disabled={startDisabled} onClick={start}>▶ Start</button>}
                {showStop  && <button className="btn-dark" onClick={stop}>■ Stop</button>}
              </div>
            </div>
          </div>

          <div>
            {/* Both divs always in DOM — canvas must stay mounted for drawing */}
            <div className="preview-empty" style={{ display: previewMode === 'empty' ? 'flex' : 'none' }}>
              <span className="icon">📷</span>
              <span className="hint">Stream will appear<br />here after starting</span>
            </div>
            <div className="preview-active" style={{ display: previewMode === 'active' ? 'block' : 'none' }}>
              <canvas ref={canvasRef}></canvas>
              <div className="live-chip"><span className="live-chip-dot"></span>LIVE</div>
            </div>
          </div>

        </div>
      </div>

      {/* Hidden video element needed to capture frames from camera stream */}
      <video ref={videoRef} autoPlay playsInline muted style={{ display: 'none' }}></video>
    </>
  );
}
