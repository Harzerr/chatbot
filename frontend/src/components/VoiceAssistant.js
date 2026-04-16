import React, { useState, useEffect, useRef } from 'react';
import { Box, Paper, IconButton, CircularProgress, Button } from '@mui/material';
import MicIcon from '@mui/icons-material/Mic';
import MicOffIcon from '@mui/icons-material/MicOff';
import CallEndIcon from '@mui/icons-material/CallEnd';

import { useLiveKit } from '../contexts/LiveKitContext';
import { useAuth } from '../contexts/AuthContext';

import { RoomEvent } from 'livekit-client';
import { RoomContext, RoomAudioRenderer, StartAudio } from '@livekit/components-react';

const safeParseJson = (rawText) => {
  if (!rawText || typeof rawText !== 'string') {
    return null;
  }
  try {
    return JSON.parse(rawText);
  } catch {
    return null;
  }
};

const getHostFromUrl = (url) => {
  if (!url || typeof url !== 'string') {
    return '';
  }
  try {
    return new URL(url).hostname || '';
  } catch {
    return '';
  }
};

const isLoopbackHost = (host) => host === 'localhost' || host === '127.0.0.1' || host === '::1';

const MIC_SAMPLE_DURATION_MS = 3500;
const MIC_SIGNAL_RMS_THRESHOLD = 0.015;
const MIC_SIGNAL_PEAK_THRESHOLD = 0.05;

const formatAudioLevel = (value) => `${Math.round(Math.min(Math.max(value, 0), 1) * 100)}%`;

const getPreferredAudioMimeType = () => {
  if (!window.MediaRecorder?.isTypeSupported) {
    return '';
  }
  return [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/ogg;codecs=opus',
    'audio/mp4'
  ].find((mimeType) => window.MediaRecorder.isTypeSupported(mimeType)) || '';
};

const formatDeviceError = (error) => {
  if (!error) {
    return '未知错误';
  }
  if (error?.name === 'NotFoundError' || error?.message?.includes('Requested device not found')) {
    return '未检测到可用麦克风，请检查设备连接。';
  }
  if (error?.name === 'NotAllowedError') {
    return '麦克风权限被拒绝，请在浏览器中允许访问麦克风。';
  }
  if (error?.name === 'NotReadableError') {
    return '麦克风可能被其他应用占用，请关闭冲突应用后重试。';
  }
  return error?.message || String(error);
};

export const DeviceCheckPanel = () => {
  const [isChecking, setIsChecking] = useState(false);
  const [checkResult, setCheckResult] = useState(null);
  const [isRecordingSample, setIsRecordingSample] = useState(false);
  const [audioTestResult, setAudioTestResult] = useState(null);
  const sampleAudioUrlRef = useRef(null);

  const revokeSampleAudioUrl = () => {
    if (sampleAudioUrlRef.current) {
      URL.revokeObjectURL(sampleAudioUrlRef.current);
      sampleAudioUrlRef.current = null;
    }
  };

  useEffect(() => () => {
    revokeSampleAudioUrl();
  }, []);

  const runCheck = async () => {
    setIsChecking(true);
    setAudioTestResult(null);
    revokeSampleAudioUrl();
    const result = {
      checkedAt: new Date().toISOString(),
      permissionState: 'unknown',
      secureContext: window.isSecureContext,
      audioInputCount: 0,
      audioOutputCount: 0,
      inputs: [],
      outputs: [],
      error: '',
    };

    let stream = null;
    try {
      if (!navigator.mediaDevices?.getUserMedia || !navigator.mediaDevices?.enumerateDevices) {
        throw new Error('当前浏览器不支持设备检测 API（getUserMedia / enumerateDevices）。');
      }

      if (navigator.permissions?.query) {
        try {
          const status = await navigator.permissions.query({ name: 'microphone' });
          result.permissionState = status.state || 'unknown';
        } catch {
          result.permissionState = 'unavailable';
        }
      }

      const devicesBeforeGrant = await navigator.mediaDevices.enumerateDevices();
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const devicesAfterGrant = await navigator.mediaDevices.enumerateDevices();
      const devices = devicesAfterGrant.length > 0 ? devicesAfterGrant : devicesBeforeGrant;

      const inputs = devices.filter((device) => device.kind === 'audioinput');
      const outputs = devices.filter((device) => device.kind === 'audiooutput');

      result.audioInputCount = inputs.length;
      result.audioOutputCount = outputs.length;
      result.inputs = inputs.map((device, index) => device.label || `麦克风 ${index + 1}`);
      result.outputs = outputs.map((device, index) => device.label || `扬声器 ${index + 1}`);

      if (result.audioInputCount === 0) {
        throw new Error('未检测到可用麦克风，请检查设备连接与系统权限。');
      }
    } catch (err) {
      result.error = `设备检测失败：${formatDeviceError(err)}`;
    } finally {
      if (stream) {
        stream.getTracks().forEach((track) => track.stop());
      }
      setCheckResult(result);
      setIsChecking(false);
    }
  };

  const runMicSampleCheck = async () => {
    if (isRecordingSample) {
      return;
    }

    setIsRecordingSample(true);
    setAudioTestResult(null);
    revokeSampleAudioUrl();

    let stream = null;
    let audioContext = null;
    let sourceNode = null;
    let animationFrameId = null;
    const levels = { peak: 0, rmsTotal: 0, samples: 0 };

    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error('当前浏览器不支持麦克风访问。');
      }
      if (!window.MediaRecorder) {
        throw new Error('当前浏览器不支持录音回放检测。');
      }

      stream = await navigator.mediaDevices.getUserMedia({ audio: true });

      const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextCtor) {
        throw new Error('当前浏览器不支持实时音量分析。');
      }

      audioContext = new AudioContextCtor();
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 2048;
      const timeDomainData = new Uint8Array(analyser.fftSize);

      sourceNode = audioContext.createMediaStreamSource(stream);
      sourceNode.connect(analyser);

      const sampleAudioLevel = () => {
        analyser.getByteTimeDomainData(timeDomainData);
        let peak = 0;
        let sumSquares = 0;
        for (let i = 0; i < timeDomainData.length; i += 1) {
          const normalized = (timeDomainData[i] - 128) / 128;
          const amplitude = Math.abs(normalized);
          peak = Math.max(peak, amplitude);
          sumSquares += normalized * normalized;
        }
        levels.peak = Math.max(levels.peak, peak);
        levels.rmsTotal += Math.sqrt(sumSquares / timeDomainData.length);
        levels.samples += 1;
        animationFrameId = window.requestAnimationFrame(sampleAudioLevel);
      };
      sampleAudioLevel();

      const chunks = [];
      const preferredMimeType = getPreferredAudioMimeType();
      const recorderOptions = preferredMimeType ? { mimeType: preferredMimeType } : undefined;
      const recorder = new MediaRecorder(stream, recorderOptions);

      await new Promise((resolve, reject) => {
        let stopTimer = null;
        recorder.ondataavailable = (event) => {
          if (event.data?.size > 0) {
            chunks.push(event.data);
          }
        };
        recorder.onerror = (event) => {
          if (stopTimer) {
            window.clearTimeout(stopTimer);
          }
          reject(event.error || new Error('录音过程中发生异常。'));
        };
        recorder.onstop = () => {
          if (stopTimer) {
            window.clearTimeout(stopTimer);
          }
          resolve();
        };
        recorder.start();
        stopTimer = window.setTimeout(() => {
          if (recorder.state !== 'inactive') {
            recorder.stop();
          }
        }, MIC_SAMPLE_DURATION_MS);
      });

      if (chunks.length === 0) {
        throw new Error('未录到可回放的音频片段。');
      }

      const audioBlob = new Blob(chunks, { type: preferredMimeType || chunks[0]?.type || 'audio/webm' });
      const audioUrl = URL.createObjectURL(audioBlob);
      sampleAudioUrlRef.current = audioUrl;

      const rms = levels.samples > 0 ? levels.rmsTotal / levels.samples : 0;
      const hasVoice = levels.peak >= MIC_SIGNAL_PEAK_THRESHOLD || rms >= MIC_SIGNAL_RMS_THRESHOLD;

      setAudioTestResult({
        checkedAt: new Date().toISOString(),
        peak: levels.peak,
        rms,
        hasVoice,
        audioUrl,
        error: '',
      });

      const playback = new Audio(audioUrl);
      playback.play().catch(() => {
        // user gesture might be required; audio control remains available in UI.
      });
    } catch (err) {
      setAudioTestResult({
        checkedAt: new Date().toISOString(),
        peak: 0,
        rms: 0,
        hasVoice: false,
        audioUrl: '',
        error: `麦克风录音检测失败：${formatDeviceError(err)}`,
      });
    } finally {
      if (animationFrameId) {
        window.cancelAnimationFrame(animationFrameId);
      }
      if (sourceNode) {
        sourceNode.disconnect();
      }
      if (audioContext && audioContext.state !== 'closed') {
        await audioContext.close().catch(() => {});
      }
      if (stream) {
        stream.getTracks().forEach((track) => track.stop());
      }
      setIsRecordingSample(false);
    }
  };

  return (
    <Paper
      elevation={0}
      sx={{
        p: 3,
        minHeight: 380,
        border: '1px solid rgba(148,163,184,0.18)',
        borderRadius: 2.5,
        background: 'linear-gradient(180deg, rgba(15,23,42,0.88) 0%, rgba(6,13,24,0.96) 100%)'
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1.4 }}>
        <Box component="div" sx={{ typography: 'h6', color: '#f8fafc' }}>
          面试前设备自检
        </Box>
       
      </Box>
      <Box sx={{ display: 'flex', gap: 1 ,mt:3}}>
          <Button
            variant="outlined"
            onClick={runMicSampleCheck}
            disabled={isRecordingSample}
            sx={{
              borderRadius: 2,
              borderColor: 'rgba(148,163,184,0.45)',
              color: '#dbeafe',
              '&:hover': { borderColor: '#93c5fd', backgroundColor: 'rgba(37,99,235,0.12)' }
            }}
          >
            {isRecordingSample ? '录音中...' : '麦克风录音检测'}
          </Button>
          <Button
            variant="contained"
            onClick={runCheck}
            disabled={isChecking}
            sx={{ borderRadius: 2 }}
          >
            {isChecking ? '检测中...' : '开始设备检测'}
          </Button>
        </Box>

      {!checkResult && !audioTestResult && (
        <Box component="div" sx={{ typography: 'body2', color: '#cbd5e1', lineHeight: 1.8 , mt:4}}>
          点击上方按钮后，系统会请求麦克风权限、检测本地音频设备，并可录制一段 3.5 秒音频用于回放确认。
        </Box>
      )}

      {checkResult && (
        <Box
          sx={{
            mt: 1,
            p: 1.5,
            borderRadius: 2,
            backgroundColor: checkResult.error ? 'rgba(248,113,113,0.10)' : 'rgba(30,41,59,0.55)',
            border: `1px solid ${checkResult.error ? 'rgba(248,113,113,0.22)' : 'rgba(148,163,184,0.18)'}`,
            color: '#dbeafe'
          }}
        >
          <Box component="div" sx={{ typography: 'body2', lineHeight: 1.8 }}>
            <div>检测时间：{new Date(checkResult.checkedAt).toLocaleString('zh-CN', { hour12: false })}</div>
            <div>安全上下文：{checkResult.secureContext ? '是' : '否'}</div>
            <div>麦克风权限：{checkResult.permissionState}</div>
            <div>音频输入设备：{checkResult.audioInputCount} 个</div>
            <div>音频输出设备：{checkResult.audioOutputCount} 个</div>
            {checkResult.inputs.length > 0 && <div>输入设备：{checkResult.inputs.join(' / ')}</div>}
            {checkResult.outputs.length > 0 && <div>输出设备：{checkResult.outputs.join(' / ')}</div>}
          </Box>
          {checkResult.error && (
            <Box component="div" sx={{ mt: 1, typography: 'body2', color: '#fecaca' }}>
              {checkResult.error}
            </Box>
          )}
        </Box>
      )}

      {audioTestResult && (
        <Box
          sx={{
            mt: 1.2,
            p: 1.5,
            borderRadius: 2,
            backgroundColor: audioTestResult.error
              ? 'rgba(248,113,113,0.10)'
              : audioTestResult.hasVoice
                ? 'rgba(34,197,94,0.10)'
                : 'rgba(234,179,8,0.12)',
            border: `1px solid ${
              audioTestResult.error
                ? 'rgba(248,113,113,0.22)'
                : audioTestResult.hasVoice
                  ? 'rgba(34,197,94,0.22)'
                  : 'rgba(234,179,8,0.24)'
            }`,
            color: '#dbeafe'
          }}
        >
          {audioTestResult.error ? (
            <Box component="div" sx={{ typography: 'body2', color: '#fecaca' }}>
              {audioTestResult.error}
            </Box>
          ) : (
            <Box component="div" sx={{ typography: 'body2', lineHeight: 1.8 }}>
              <div>录音检测结果：{audioTestResult.hasVoice ? '检测到有效声音' : '声音偏弱，请靠近麦克风再试'}</div>
              <div>峰值音量：{formatAudioLevel(audioTestResult.peak)}</div>
              <div>平均能量：{formatAudioLevel(audioTestResult.rms)}</div>
              {audioTestResult.audioUrl && (
                <Box component="audio" controls src={audioTestResult.audioUrl} sx={{ mt: 1.1, width: '100%' }} />
              )}
            </Box>
          )}
        </Box>
      )}
    </Paper>
  );
};
const VoiceAssistant = ({
  interviewContext = null,
  onMessagesChange,
}) => {
  const [isListening, setIsListening] = useState(false);
  const [transcript, setTranscript] = useState('');
  const [response, setResponse] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [messages, setMessages] = useState([]);
  const [textInput, setTextInput] = useState('');
  const messagesEndRef = useRef(null);
  const seenFinalTranscriptionKeysRef = useRef(new Set());
  const seenAssistantChatKeysRef = useRef(new Set());
  const { 
    room, 
    isConnected, 
    connect, 
    disconnect, 
    error, 
    setError, 
    logConnectionDetails,
    transcriptions,
    chatMessages,
    agentState,
    sendChatMessage
  } = useLiveKit();
  const { token: authToken, tokenType } = useAuth();

  const handleDisconnect = async () => {
    try {
      console.log('棣冩暥 Disconnecting from LiveKit room...');

      if (room && room.localParticipant) {
        await room.localParticipant.setMicrophoneEnabled(false);
      }

      disconnect();

      setIsListening(false);
      setTranscript('');
      setResponse('');
      setIsSpeaking(false);
      seenFinalTranscriptionKeysRef.current.clear();
      seenAssistantChatKeysRef.current.clear();

      setMessages(prevMessages => [
        ...prevMessages,
        {
          id: `system-${Date.now()}`,
          text: '语音通话已结束',
          isSystem: true,
          timestamp: new Date().toISOString()
        }
      ]);
      
      console.log('Voice call ended');
    } catch (error) {
      console.error('Error disconnecting:', error);
    }
  };

  const handleSendMessage = () => {
    if (textInput.trim() && isConnected) {
      setMessages(prevMessages => [
        ...prevMessages,
        {
          id: `user-${Date.now()}`,
          text: textInput,
          isUser: true,
          role: 'candidate',
          timestamp: new Date().toISOString()
        }
      ]);

      sendChatMessage(textInput);

      setTextInput('');
    }
  };
  
  const toggleMicrophone = async () => {
    if (!isConnected) {
      try {
        const resolvedToken = authToken || localStorage.getItem('token');
        if (!resolvedToken) {
          setError('登录状态已失效，请重新登录后再开始语音面试。');
          return;
        }

        setError(null);
        
        console.log('Starting LiveKit connection process');
        setIsLoading(true);

        console.log('Fetching token from backend...');
        const response = await fetch('/api/v1/livekit/generate_token', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `${tokenType || 'Bearer'} ${resolvedToken}`
          },
          body: JSON.stringify({
            chat_id: interviewContext?.chatId || null,
            interview_role: interviewContext?.interviewRole || null,
            interview_level: interviewContext?.interviewLevel || null,
            interview_type: interviewContext?.interviewType || null,
            target_company: interviewContext?.targetCompany || null,
            jd_content: interviewContext?.jdContent || null,
          }),
        });
        
        if (!response.ok) {
          const errorText = await response.text();
          console.error('Failed to fetch token:', response.status, errorText);
          const parsedError = safeParseJson(errorText);
          const detail = parsedError?.detail;
          const backendMessage = typeof detail === 'string' ? detail : errorText;
          setError(backendMessage || `获取 LiveKit token 失败：${response.status}`);
          setIsLoading(false);
          return;
        }
        
        const data = await response.json();
        console.log('棣冩憹 Received from backend:', {
          hasToken: !!data.token,
          tokenLength: data.token ? data.token.length : 0,
          roomName: data.room_name,
          liveKitUrl: data.livekit_url
        });

        const liveKitUrl = data.livekit_url || process.env.REACT_APP_LIVEKIT_URL;
        console.log('棣冨 LiveKit URL from env:', liveKitUrl);
        
        if (!liveKitUrl) {
          console.error('LiveKit URL not found in environment variables');
          setError('LiveKit 地址未配置');
          setIsLoading(false);
          return;
        }

        const pageHost = window.location.hostname;
        const liveKitHost = getHostFromUrl(liveKitUrl);
        if (liveKitHost && isLoopbackHost(liveKitHost) && !isLoopbackHost(pageHost)) {
          const mismatchHint = `当前页面主机是 ${pageHost}，但 LiveKit 地址主机是 ${liveKitHost}。如果你是远程访问，请把 LIVEKIT_PUBLIC_URL 改为客户端可达地址。`;
          setMessages(prevMessages => [
            ...prevMessages,
            {
              id: `error-${Date.now()}`,
              text: mismatchHint,
              isSystem: true,
              isError: true,
              timestamp: new Date().toISOString()
            }
          ]);
        }

        console.log('棣冩敡 Connecting to LiveKit room:', {
          url: liveKitUrl,
          roomName: data.room_name,
          hasToken: !!data.token
        });
        
        const connectedRoom = await connect(liveKitUrl, data.token);
        
        if (!connectedRoom) {
          console.error('Failed to connect to LiveKit room');
          setError(error || '连接 LiveKit 房间失败');
          setIsLoading(false);
          return;
        }
        
        console.log('Connected to LiveKit room:', connectedRoom.name);

        if (connectedRoom.localParticipant) {
          console.log('Enabling microphone...');
          console.log('棣冩敵 Room state:', {
            name: connectedRoom.name,
            sid: connectedRoom.sid,
            connectionState: connectedRoom.connectionState,
            localParticipant: connectedRoom.localParticipant ? connectedRoom.localParticipant.identity : 'Not available'
          });
          
          await connectedRoom.localParticipant.setMicrophoneEnabled(true);
          console.log('Microphone enabled successfully');
          setIsListening(true);

          setMessages(prevMessages => [
            ...prevMessages,
            {
              id: `system-${Date.now()}`,
              text: '语音通话已连接',
              isSystem: true,
              timestamp: new Date().toISOString()
            }
          ]);
        } else {
          console.error('Room object not available after connection');
          setError('语音房间初始化失败');
        }
      } catch (error) {
        console.error('Error connecting to LiveKit room:', error);
        const message = error?.message || `连接异常：${String(error)}`;
        setError(message);

        setMessages(prevMessages => [
          ...prevMessages,
          {
            id: `error-${Date.now()}`,
            text: message,
            isSystem: true,
            isError: true,
            timestamp: new Date().toISOString()
          }
        ]);
      } finally {
        setIsLoading(false);
      }
    } else {
      try {
        if (isListening) {
          await room.localParticipant.setMicrophoneEnabled(false);
          setIsListening(false);
        } else {
          await room.localParticipant.setMicrophoneEnabled(true);
          setIsListening(true);
        }
      } catch (error) {
        console.error('Error toggling microphone:', error);
      }
    }
  };

  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages]);

  useEffect(() => {
    if (typeof onMessagesChange === 'function') {
      onMessagesChange(messages);
    }
  }, [messages, onMessagesChange]);

  useEffect(() => {
    if (transcriptions.length > 0) {
      const latestTranscription = transcriptions[transcriptions.length - 1];
      console.log('Received transcription:', latestTranscription);

      const text = String(latestTranscription.text || latestTranscription.message || '').trim();
      if (!text) {
        return;
      }

      // Only render final transcription bubbles to avoid repeated partial updates.
      const isFinal = latestTranscription.isFinal === undefined ? true : Boolean(latestTranscription.isFinal);
      if (!isFinal) {
        return;
      }

      const normalizedRole =
        latestTranscription.role === 'assistant' || latestTranscription.role === 'interviewer'
          ? 'interviewer'
          : 'candidate';
      const dedupeKey = [
        'transcription',
        normalizedRole,
        latestTranscription.participantIdentity || '',
        latestTranscription.id || '',
        text,
      ].join('|');
      if (seenFinalTranscriptionKeysRef.current.has(dedupeKey)) {
        return;
      }
      seenFinalTranscriptionKeysRef.current.add(dedupeKey);

      setMessages(prevMessages => {
        const lastMessage = prevMessages[prevMessages.length - 1];
        if (
          lastMessage &&
          !lastMessage.isSystem &&
          lastMessage.role === normalizedRole &&
          String(lastMessage.text || '').trim() === text
        ) {
          return prevMessages;
        }
        return [
          ...prevMessages,
          {
            id: `transcription-${latestTranscription.id || Date.now()}`,
            text,
            isUser: normalizedRole === 'candidate',
            role: normalizedRole,
            timestamp: latestTranscription.timestamp || new Date().toISOString()
          }
        ];
      });
    }
  }, [transcriptions]);

  useEffect(() => {
    if (chatMessages.length > 0) {
      const latestMessage = chatMessages[chatMessages.length - 1];
      console.log('Received chat message:', latestMessage);

      if (latestMessage.sender !== 'user') {
        const text = String(latestMessage.message || '').trim();
        if (!text) {
          return;
        }
        const dedupeKey = [
          'assistant-chat',
          latestMessage.sender || '',
          latestMessage.id || '',
          latestMessage.timestamp || '',
          text,
        ].join('|');
        if (seenAssistantChatKeysRef.current.has(dedupeKey)) {
          return;
        }
        seenAssistantChatKeysRef.current.add(dedupeKey);

        setMessages(prevMessages => {
          const lastMessage = prevMessages[prevMessages.length - 1];
          if (
            lastMessage &&
            !lastMessage.isSystem &&
            lastMessage.role === 'interviewer' &&
            String(lastMessage.text || '').trim() === text
          ) {
            return prevMessages;
          }
          return [
            ...prevMessages,
            {
              id: `chat-${Date.now()}`,
              text,
              isUser: false,
              role: 'interviewer',
              timestamp: latestMessage.timestamp || new Date().toISOString()
            }
          ];
        });
      }
    }
  }, [chatMessages]);

  useEffect(() => {
    console.log('Agent state updated:', agentState);
    setIsSpeaking(agentState === 'speaking');
    setIsListening(agentState === 'listening' || isListening);
  }, [agentState, isListening]);

  const formatTime = (timestamp) => {
    const date = new Date(timestamp);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  const resolveMessageRole = (message) => {
    if (message.role === 'candidate' || message.role === 'interviewer') {
      return message.role;
    }
    return message.isUser ? 'candidate' : 'interviewer';
  };

  const getMessageStyle = (role) => {
    if (role === 'candidate') {
      return {
        label: '\u5019\u9009\u4eba',
        justifyContent: 'flex-end',
        alignItems: 'flex-end',
        bubbleBg: '#dbeafe',
        bubbleText: '#111111',
        metaText: '#111111',
        borderColor: 'rgba(30,64,175,0.25)',
        tailSide: 'right',
      };
    }

    return {
      label: '\u9762\u8bd5\u5b98',
      justifyContent: 'flex-start',
      alignItems: 'flex-start',
      bubbleBg: '#ccfbf1',
      bubbleText: '#111111',
      metaText: '#111111',
      borderColor: 'rgba(13,148,136,0.28)',
      tailSide: 'left',
    };
  };

  const renderMessage = (message) => {
    if (message.isSystem) {
      if (message.isError) {
        return (
          <Box
            key={message.id}
            sx={{
              textAlign: 'center',
              py: 1.5,
              my: 2,
              borderTop: '1px dashed rgba(92, 107, 192, 0.3)',
              borderBottom: '1px dashed rgba(92, 107, 192, 0.3)',
              bgcolor: 'rgba(92, 107, 192, 0.05)',
              borderRadius: 1
            }}
          >
            <Box
              component='div'
              sx={{
                fontStyle: 'italic',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 0.5,
                typography: 'caption',
                color: '#5C6BC0'
              }}
            >
              [Error] {message.text}
            </Box>
          </Box>
        );
      }

      return (
        <Box
          key={message.id}
          sx={{
            textAlign: 'center',
            py: 1.5,
            my: 2,
            borderTop: '1px dashed rgba(0, 0, 0, 0.1)',
            borderBottom: '1px dashed rgba(0, 0, 0, 0.1)'
          }}
        >
          <Box component='div' sx={{
            fontStyle: 'italic',
            typography: 'caption',
            color: 'text.secondary'
          }}>
            {message.text}
          </Box>
        </Box>
      );
    }

    const role = resolveMessageRole(message);
    const style = getMessageStyle(role);

    return (
      <Box
        key={message.id}
        sx={{
          display: 'flex',
          justifyContent: style.justifyContent,
          width: '100%',
          px: { xs: 0.5, sm: 1 },
          mb: 2,
        }}
      >
        <Box
          sx={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: style.alignItems,
            maxWidth: { xs: '92%', sm: '82%' },
            width: 'fit-content',
          }}
        >
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              mb: 0.5,
              px: 0.4,
              gap: 0.8,
              color: style.metaText,
            }}
          >
            <Box component='span' sx={{ fontWeight: 700, typography: 'caption' }}>
              {style.label}
            </Box>
            <Box component='span' sx={{ opacity: 0.9, typography: 'caption' }}>
              {formatTime(message.timestamp)}
            </Box>
          </Box>
          <Paper
            elevation={0}
            sx={{
              p: 2,
              width: 'fit-content',
              maxWidth: '100%',
              bgcolor: style.bubbleBg,
              color: style.bubbleText,
              borderRadius: style.tailSide === 'right' ? '16px 16px 6px 16px' : '16px 16px 16px 6px',
              border: '1px solid ' + style.borderColor,
              position: 'relative',
              boxShadow: '0 6px 20px rgba(2, 6, 23, 0.22)',
              '&::after': style.tailSide === 'right'
                ? {
                    content: '" "',
                    position: 'absolute',
                    bottom: 0,
                    right: -8,
                    width: 15,
                    height: 15,
                    backgroundColor: style.bubbleBg,
                    borderBottomLeftRadius: '50%',
                    transform: 'translateY(30%)',
                    borderRight: '1px solid ' + style.borderColor,
                    borderBottom: '1px solid ' + style.borderColor,
                  }
                : {
                    content: '" "',
                    position: 'absolute',
                    bottom: 0,
                    left: -8,
                    width: 15,
                    height: 15,
                    backgroundColor: style.bubbleBg,
                    borderBottomRightRadius: '50%',
                    transform: 'translateY(30%)',
                    borderLeft: '1px solid ' + style.borderColor,
                    borderBottom: '1px solid ' + style.borderColor,
                  },
            }}
          >
            <Box component='div' sx={{
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              lineHeight: 1.5
            }}>
              {message.text}
            </Box>
          </Paper>
        </Box>
      </Box>
    );
  };
  useEffect(() => {
    if (!room) return;

    const handleDataReceived = (payload) => {
      try {
        const data = JSON.parse(new TextDecoder().decode(payload));
        console.log('Received data message:', data);

        // transcript/response are handled via LiveKitContext -> transcriptions/chatMessages.
        // Keep only error handling here to avoid duplicate bubbles.
        if (data.type === 'error') {
          console.error('Error from LiveKit agent:', data.text);
          setError(data.text);

          const errorMessage = {
            id: `error-${Date.now()}`,
            text: data.text,
            isSystem: true,
            isError: true,
            timestamp: new Date().toISOString()
          };

          setMessages(prevMessages => [...prevMessages, errorMessage]);

          if (room.localParticipant) {
            room.localParticipant.setMicrophoneEnabled(false);
            setIsListening(false);
          }
        }
      } catch (error) {
        console.error('Error parsing data message:', error);
      }
    };

    room.on(RoomEvent.DataReceived, handleDataReceived);

    return () => {
      room.off(RoomEvent.DataReceived, handleDataReceived);
    };
  }, [room, setError]);

  useEffect(() => {
    return () => {
      disconnect();
    };
  }, [disconnect]);

  return (
    <>
      {/* Conditionally render LiveKit components when connected */}
      {isConnected && room && (
        <RoomContext.Provider value={room}>
          <RoomAudioRenderer />
          <StartAudio label="开启音频" />
        </RoomContext.Provider>
      )}
      
      <Paper 
        elevation={3} 
        sx={{ 
          width: '100%', 
          maxWidth: 700, 
          mx: 'auto', 
          height: '70vh', 
          display: 'flex', 
          flexDirection: 'column',
          overflow: 'hidden',
          borderRadius: 2
        }}
      >
     
      
      {isConnected ? (
        <>
          {/* Messages area with scrolling */}
          <Box sx={{ 
            flexGrow: 1, 
            overflowY: 'auto', 
            mb: 2, 
            p: 2,
            display: 'flex',
            flexDirection: 'column'
          }}>
            {}
            <Box sx={{ 
              p: 4, 
              display: 'flex', 
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              mb: messages.length > 0 ? 4 : 0
            }}>
              <Box sx={{ 
                display: 'flex', 
                flexDirection: 'column', 
                alignItems: 'center', 
                justifyContent: 'center',
                opacity: 0.8
              }}>
                <MicIcon sx={{ fontSize: 48, color: 'primary.main', opacity: 0.6, mb: 2 }} />
                <Box component="div" sx={{ fontWeight: 'medium', mb: 1, textAlign: 'center', typography: 'body1', color: 'text.primary' }}>
                  语音助手已就绪
                </Box>
                <Box component="div" sx={{ maxWidth: '80%', textAlign: 'center', typography: 'body2', color: 'text.secondary' }}>
                  你的语音面试对话会显示在这里。
                  <br />
                  点击下方麦克风按钮即可开始作答。
                </Box>
              </Box>
            </Box>
            
            {}
            {messages.length > 0 && (
              <Box sx={{ width: '100%' }}>
                {messages.map(renderMessage)}
              </Box>
            )}
            <div ref={messagesEndRef} />
          </Box>
          
          {/* Status area removed */}
          
          {/* Control bar */}
          <Box sx={{ 
            display: 'flex', 
            alignItems: 'center', 
            justifyContent: 'center',
            borderTop: 1,
            borderColor: 'divider',
            pt: 3,
            mt: 2,
            pb: 1,
            px: 10,
            gap: 3
          }}>
            {/* Text input removed but logic preserved */}

            <IconButton 
              color={isListening ? "secondary" : "primary"}
              onClick={toggleMicrophone}
              disabled={isLoading}
              size="large"
              sx={{ 
                p: 3, 
                border: 2, 
                borderColor: isListening ? 'secondary.main' : 'primary.main',
                boxShadow: isListening ? '0 0 15px rgba(156, 39, 176, 0.5)' : '0 4px 8px rgba(25, 118, 210, 0.25)',
                transition: 'all 0.3s ease',
                '&:hover': {
                  backgroundColor: isListening ? 'rgba(156, 39, 176, 0.08)' : 'rgba(25, 118, 210, 0.08)',
                  transform: 'scale(1.05)'
                }
              }}
            >
              {isListening ? <MicIcon /> : <MicOffIcon />}
            </IconButton>
            
            <Button 
              variant="contained" 
              color="primary" 
              startIcon={<CallEndIcon />}
              onClick={handleDisconnect}
              sx={{
                px: 4,
                py: 1.2,
                borderRadius: 28,
                backgroundColor: '#5C6BC0', // Indigo color instead of red
                boxShadow: '0 4px 12px rgba(92, 107, 192, 0.3)',
                '&:hover': {
                  backgroundColor: '#3F51B5',
                  transform: 'translateY(-2px)',
                  boxShadow: '0 6px 14px rgba(92, 107, 192, 0.4)'
                },
                transition: 'all 0.2s ease'
              }}
            >
              结束通话
            </Button>
          </Box>
        </>
      ) : (
        <Box sx={{ 
          display: 'flex', 
          flexDirection: 'column', 
          alignItems: 'center', 
          justifyContent: 'center',
          flexGrow: 1,
          gap: 3 
        }}>
          <Box sx={{ textAlign: 'center', mb: 2 }}>
            <MicIcon sx={{ fontSize: 64, color: error ? 'error.main' : 'primary.main', opacity: 0.8, mb: 2 }} />
            <Box component="div" sx={{ typography: 'h6', textAlign: 'center', mb: 1 }}>
              语音面试助手
            </Box>
            <Box component="div" sx={{ typography: 'body1', textAlign: 'center', color: 'text.secondary', maxWidth: '80%', mx: 'auto' }}>
              {error ? (
                <Box sx={{ color: 'error.main', mt: 1, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                  <Box component="div" sx={{ fontWeight: 'medium', mb: 1, typography: 'body2', color: '#5C6BC0' }}>
                    {error}
                  </Box>
                  <Box component="div" sx={{ typography: 'body2', color: 'text.secondary' }}>
                    请稍后重试，或检查网络与服务连接
                  </Box>
                </Box>
              ) : (
                <Box component="div" sx={{ typography: 'body1', textAlign: 'center', color: 'text.secondary' }}>
                  开始与 AI 面试官进行语音面试
                </Box>
              )}
            </Box>
          </Box>
          
          <Button 
            variant="contained" 
            color="primary" 
            size="large"
            onClick={toggleMicrophone}
            disabled={isLoading}
            sx={{ 
              py: 1.5, 
              px: 4, 
              borderRadius: 28,
              boxShadow: 3,
              '&:hover': {
                transform: 'translateY(-2px)',
                boxShadow: 4
              },
              transition: 'all 0.3s ease'
            }}
            startIcon={<MicIcon />}
          >
            {isLoading ? <CircularProgress size={24} /> : '开始语音面试'}
          </Button>
        </Box>
      )}
      
      
    </Paper>
    </>
  );
};

export default VoiceAssistant;
