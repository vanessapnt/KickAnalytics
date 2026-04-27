import { useRef, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { getWsBase } from '../utils/wsBase';

export function useControllerWs() {
  const wsRef = useRef(null);
  const openedRef = useRef(false);
  const navigate = useNavigate();

  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [match, setMatch] = useState({ red: [], blue: [], mode: '1v1' });
  const [score, setScore] = useState({ red: 0, blue: 0 });
  const [status, setStatus] = useState({ text: 'Déconnecté', type: '' });
  const [previewMode, setPreviewMode] = useState('empty'); // 'empty' | 'image' | 'none'
  const [previewImage, setPreviewImage] = useState(null);
  const [previewHint, setPreviewHint] = useState(false);
  const [showCalibrationButtons, setShowCalibrationButtons] = useState(false);
  const [showStop, setShowStop] = useState(false);
  const [showReplay, setShowReplay] = useState(false);
  const [eloData, setEloData] = useState(null);

  const sendWs = useCallback((msg) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg));
    }
  }, []);

  const triggerCalibration = useCallback(() => {
    sendWs({ type: 'trigger_calibration' });
    setPreviewMode('empty');
    setShowCalibrationButtons(false);
    setPreviewHint(false);
    setStatus({ text: '🔍 Détection terrain...', type: '' });
  }, [sendWs]);

  const connect = useCallback(() => {
    const ws = wsRef.current;
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      setConnecting(false);
      return;
    }
    setConnecting(true);
    openedRef.current = false;

    const newWs = new WebSocket(`${getWsBase()}/controller`);
    wsRef.current = newWs;

    newWs.onopen = () => {
      openedRef.current = true;
      setConnected(true);
      setConnecting(false);
      setStatus({ text: 'Connecté', type: 'ok' });
    };

    newWs.onclose = () => {
      setConnected(false);
      setConnecting(false);
      if (!openedRef.current) {
        setStatus({ text: 'Connexion refusée (auth requise)', type: 'err' });
        setTimeout(() => navigate('/'), 900);
        return;
      }
      setShowCalibrationButtons(false);
      setPreviewHint(false);
      setStatus({ text: 'Déconnecté', type: '' });
    };

    newWs.onmessage = (e) => {
      const d = JSON.parse(e.data);

      if (d.type === 'mm_start' && d.match) {
        setMatch(d.match);
      }
      if (d.type === 'table_status') {
        const hasCamera = d.camera_pool && d.camera_pool.length > 0;
        const activeState = ['calibrating', 'playing', 'waiting_camera'].includes(d.state);
        if (activeState && (hasCamera || d.state !== 'waiting_camera')) {
          if (d.state !== 'playing') setStatus({ text: '📱 Caméra prête', type: '' });
        }
      }
      if (['camera_ready', 'camera_selected', 'camera_reselected'].includes(d.type)) {
        setStatus({ text: '📱 Caméra prête', type: '' });
      }
      if (d.type === 'camera_resumed') {
        setStatus({ text: '▶ Match repris', type: 'ok' });
      }
      if (d.type === 'calibration_preview') {
        setPreviewImage(d.image);
        setPreviewMode('image');
        setShowCalibrationButtons(true);
        setPreviewHint(false);
        setStatus({ text: 'Vérifie le contour', type: '' });
      }
      if (d.type === 'calibration_ok') {
        setPreviewMode('none');
        setShowCalibrationButtons(false);
        setPreviewHint(false);
        setStatus({ text: '🟢 Match en cours', type: 'ok' });
        setShowStop(true);
      }
      if (d.type === 'calibration_failed') {
        if (d.image) {
          setPreviewImage(d.image);
          setPreviewMode('image');
          setShowCalibrationButtons(true);
          setPreviewHint(true);
        } else {
          setPreviewMode('empty');
          setShowCalibrationButtons(false);
          setPreviewHint(false);
        }
        setStatus({ text: '❌ Échec, ajuste la caméra puis réessaie', type: 'err' });
      }
      if (d.type === 'goal' && d.score) {
        setScore({ red: d.score.red, blue: d.score.blue });
      }
      if (d.type === 'match_end') {
        setScore({ red: d.score.red, blue: d.score.blue });
        setStatus({ text: '🏁 Match terminé', type: '' });
        setPreviewMode('none');
        setPreviewHint(false);
        setShowStop(false);
        setShowReplay(true);
      }
      if (d.type === 'elo_update') {
        setEloData(d);
      }
    };
  }, [navigate, triggerCalibration]);

  const confirmCalibration = useCallback(() => {
    sendWs({ type: 'confirm_calibration' });
    setPreviewMode('none');
    setShowCalibrationButtons(false);
    setPreviewHint(false);
    setStatus({ text: '🟢 Match en cours', type: 'ok' });
  }, [sendWs]);

  const stopMatch = useCallback(() => {
    if (!confirm('Arrêter le match en cours ? Le score actuel sera enregistré.')) return;
    sendWs({ type: 'force_end_match' });
    setShowStop(false);
  }, [sendWs]);

  const replayMatch = useCallback(() => {
    setShowReplay(false);
    setShowStop(false);
    setEloData(null);
    setScore({ red: 0, blue: 0 });
    triggerCalibration();
  }, [triggerCalibration]);

  const leaveController = useCallback((event) => {
    if (event) event.preventDefault();
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      try { ws.send(JSON.stringify({ type: 'mm_leave_match' })); } catch (_) {}
      try { ws.close(); } catch (_) {}
      setTimeout(() => navigate('/'), 100);
      return;
    }
    navigate('/');
  }, [navigate]);

  return {
    connected,
    connecting,
    match,
    score,
    status,
    previewMode,
    previewImage,
    previewHint,
    showCalibrationButtons,
    showStop,
    showReplay,
    eloData,
    connect,
    triggerCalibration,
    confirmCalibration,
    stopMatch,
    replayMatch,
    leaveController,
  };
}
