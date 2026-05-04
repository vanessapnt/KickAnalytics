import { useRef, useState, useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { getWsBase } from '../utils/wsBase';

export function useControllerWs() {
  const wsRef    = useRef(null);
  const openedRef = useRef(false);
  const navigate = useNavigate();

  const [connecting, setConnecting] = useState(false);
  const [match,  setMatch]  = useState({ red: [], blue: [], mode: '1v1' });
  const [score,  setScore]  = useState({ red: 0, blue: 0 });
  const [status, setStatus] = useState({ text: 'Disconnected', type: '' });
  const [previewMode, setPreviewMode] = useState('empty');
  const [previewImage, setPreviewImage] = useState(null);
  const [previewHint,  setPreviewHint]  = useState(false);
  const [showCalibrationButtons, setShowCalibrationButtons] = useState(false);
  const [showStop,   setShowStop]   = useState(true);
  const [showReplay, setShowReplay] = useState(false);
  const [eloData,    setEloData]    = useState(null);

  const sendWs = useCallback((msg) => {
    if (wsRef.current?.readyState === WebSocket.OPEN)
      wsRef.current.send(JSON.stringify(msg));
  }, []);

  const triggerCalibration = useCallback(() => {
    sendWs({ type: 'trigger_calibration' });
    setPreviewMode('empty');
    setShowCalibrationButtons(false);
    setPreviewHint(false);
    setStatus({ text: '🔍 Detecting field...', type: '' });
  }, [sendWs]);

  const connect = useCallback(() => {
    const ws = wsRef.current;
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      setConnecting(false); return;
    }
    setConnecting(true);
    openedRef.current = false;

    const newWs = new WebSocket(`${getWsBase()}/controller`);
    wsRef.current = newWs;

    newWs.onopen = () => {
      openedRef.current = true;
      setConnecting(false);
      setStatus({ text: 'Connected', type: 'ok' });
    };

    newWs.onclose = () => {
      setConnecting(false);
      if (!openedRef.current) {
        setStatus({ text: 'Connection refused (auth required)', type: 'err' });
        setTimeout(() => navigate('/'), 900);
        return;
      }
      setShowCalibrationButtons(false);
      setPreviewHint(false);
      setStatus({ text: 'Disconnected', type: '' });
    };

    newWs.onmessage = (e) => {
      const d = JSON.parse(e.data);

      if (d.type === 'table_status') {
        if (d.match?.red?.length) setMatch(d.match);
        if (d.score) setScore({ red: d.score.red ?? 0, blue: d.score.blue ?? 0 });
        if (d.camera_connected) setStatus({ text: '📱 Camera connected', type: '' });
      }
      if (d.type === 'calibration_preview') {
        setPreviewImage(d.image);
        setPreviewMode('image');
        setShowCalibrationButtons(true);
        setPreviewHint(false);
        setStatus({ text: 'Check the outline', type: '' });
      }
      if (d.type === 'calibration_ok') {
        setPreviewMode('none');
        setShowCalibrationButtons(false);
        setPreviewHint(false);
        setStatus({ text: '🟢 Match in progress', type: 'ok' });
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
        setStatus({ text: '❌ Failed, adjust camera and retry', type: 'err' });
      }
      if (d.type === 'match_paused') {
        setStatus({ text: '⏸ Match paused (camera disconnected)', type: 'err' });
      }
      if (d.type === 'goal' && d.score) {
        setScore({ red: d.score.red, blue: d.score.blue });
      }
      if (d.type === 'match_end') {
        setScore({ red: d.score.red, blue: d.score.blue });
        setStatus({ text: '🏁 Match over', type: '' });
        setPreviewMode('none');
        setPreviewHint(false);
        setShowStop(false);
        setShowReplay(true);
      }
      if (d.type === 'elo_update') setEloData(d);
    };
  }, [navigate]);

  const confirmCalibration = useCallback(() => {
    sendWs({ type: 'confirm_calibration' });
    setPreviewMode('none');
    setShowCalibrationButtons(false);
    setPreviewHint(false);
    setStatus({ text: '🟢 Match in progress', type: 'ok' });
  }, [sendWs]);

  const stopMatch = useCallback(() => {
    if (!confirm('Stop the current match? The current score will be saved.')) return;
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
    wsRef.current?.close();
    navigate('/');
  }, [navigate]);

  useEffect(() => { connect(); }, [connect]);

  useEffect(() => {
    if (!navigator.locks) return;
    const ctrl = new AbortController();
    navigator.locks.request(
      'controller-ws-active',
      { mode: 'shared', signal: ctrl.signal },
      () => new Promise(() => {})
    ).catch(() => {});
    return () => ctrl.abort();
  }, []);

  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState !== 'visible') return;
      const ws = wsRef.current;
      if (!ws || ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING) {
        connect();
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);
    return () => document.removeEventListener('visibilitychange', handleVisibility);
  }, [connect]);

  return {
    connecting, match, score, status,
    previewMode, previewImage, previewHint,
    showCalibrationButtons, showStop, showReplay, eloData,
    connect, triggerCalibration, confirmCalibration,
    stopMatch, replayMatch, leaveController,
  };
}
