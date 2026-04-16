import React, { createContext, useCallback, useContext, useState } from 'react';
import { DataPacket_Kind, Room, RoomEvent } from 'livekit-client';

const LiveKitContext = createContext(null);
const TRANSCRIPTION_TOPIC = 'lk.transcription';

const isFinalAttribute = (value) => value === true || value === 'true';

const normalizeLiveKitRtcUrl = (url) => {
  if (!url || typeof url !== 'string') {
    return url;
  }

  const trimmedUrl = url.trim();
  if (trimmedUrl.startsWith('https://')) {
    return `wss://${trimmedUrl.slice('https://'.length)}`;
  }
  if (trimmedUrl.startsWith('http://')) {
    return `ws://${trimmedUrl.slice('http://'.length)}`;
  }
  return trimmedUrl;
};

const getHostFromUrl = (url) => {
  if (!url || typeof url !== 'string') {
    return '';
  }
  try {
    return new URL(url).host;
  } catch {
    return '';
  }
};

const getHostnameFromUrl = (url) => {
  if (!url || typeof url !== 'string') {
    return '';
  }
  try {
    return new URL(url).hostname;
  } catch {
    return '';
  }
};

const isLoopbackHost = (host) => {
  const normalizedHost = (host || '').toLowerCase();
  return normalizedHost === 'localhost' || normalizedHost === '127.0.0.1' || normalizedHost === '::1';
};

const withHostname = (url, hostname) => {
  if (!url || !hostname) {
    return '';
  }
  try {
    const parsed = new URL(url);
    parsed.hostname = hostname;
    return parsed.toString();
  } catch {
    return '';
  }
};

const withWssSchemeIfNeeded = (url) => {
  if (!url || typeof url !== 'string') {
    return '';
  }
  if (url.startsWith('ws://')) {
    return `wss://${url.slice('ws://'.length)}`;
  }
  return '';
};

const buildConnectCandidates = (normalizedUrl) => {
  const pageProtocol = window.location.protocol;
  const pageHostname = window.location.hostname;
  const rtcHostname = getHostnameFromUrl(normalizedUrl);
  const candidates = [];
  const seen = new Set();

  const pushCandidate = (candidate) => {
    if (!candidate || seen.has(candidate)) {
      return;
    }
    seen.add(candidate);
    candidates.push(candidate);
  };

  pushCandidate(normalizedUrl);

  // If backend returns a stale/incorrect host, try current page hostname as fallback.
  if (
    rtcHostname &&
    pageHostname &&
    rtcHostname.toLowerCase() !== pageHostname.toLowerCase()
  ) {
    pushCandidate(withHostname(normalizedUrl, pageHostname));
  }

  if (pageProtocol === 'https:') {
    candidates.slice().forEach((candidate) => {
      pushCandidate(withWssSchemeIfNeeded(candidate));
    });
  }

  return candidates;
};

const buildConnectErrorMessage = (error, normalizedUrl, attemptedUrls = []) => {
  const host = getHostFromUrl(normalizedUrl) || normalizedUrl || '<empty-url>';
  const attempts = attemptedUrls.length > 0 ? `；尝试地址：${attemptedUrls.join(', ')}` : '';
  const base = error?.message || String(error) || '未知连接错误';
  return `连接 LiveKit 房间失败（${host}）：${base}${attempts}`;
};

export function useLiveKit() {
  const context = useContext(LiveKitContext);
  if (!context) {
    throw new Error('useLiveKit must be used within a LiveKitProvider');
  }
  return context;
}

export function LiveKitProvider({ children }) {
  const [room, setRoom] = useState(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [error, setError] = useState(null);
  const [connectionDetails, setConnectionDetails] = useState(null);
  const [transcriptions, setTranscriptions] = useState([]);
  const [chatMessages, setChatMessages] = useState([]);
  const [agentState, setAgentState] = useState('disconnected');

  const connect = useCallback(async (url, token) => {
    if (isConnecting) {
      return null;
    }

    const normalizedUrl = normalizeLiveKitRtcUrl(url);
    const connectCandidates = buildConnectCandidates(normalizedUrl);
    try {
      setIsConnecting(true);
      setError(null);
      console.log('[livekit] connect attempt', {
        url: normalizedUrl,
        candidates: connectCandidates,
        urlHost: getHostFromUrl(normalizedUrl),
        pageHost: window.location.host,
        tokenLength: token ? token.length : 0,
      });

      const newRoom = new Room();

      const appendTranscription = (entry) => {
        if (!entry.text || entry.text.trim() === '') {
          return;
        }

        setTranscriptions((prev) => [
          ...prev,
          {
            timestamp: new Date().toISOString(),
            ...entry,
          },
        ]);
      };

      const getParticipantRole = (participantIdentity) => {
        if (participantIdentity && participantIdentity === newRoom.localParticipant.identity) {
          return 'user';
        }
        if (participantIdentity?.startsWith('user_')) {
          return 'user';
        }
        return 'assistant';
      };

      newRoom.on(RoomEvent.DataReceived, (payload, participant, kind) => {
        if (kind !== DataPacket_Kind.RELIABLE) {
          return;
        }

        try {
          const data = JSON.parse(new TextDecoder().decode(payload));
          console.log('[livekit] data received', data);

          if (data.type === 'transcription') {
            const participantIdentity = data.participantIdentity || participant?.identity || '';
            appendTranscription({
              ...data,
              participantIdentity,
              role: data.role || getParticipantRole(participantIdentity),
              source: data.source || 'data-message',
            });
          } else if (data.type === 'chat') {
            setChatMessages((prev) => [...prev, data]);
          } else if (data.type === 'agent_state') {
            setAgentState(data.state);
            console.log('[livekit] agent state changed', data.state);
          }
        } catch (parseError) {
          console.error('[livekit] failed to parse data packet', parseError);
        }
      });

      newRoom.on(RoomEvent.ParticipantConnected, (participant) => {
        console.log('[livekit] participant connected', participant.identity);
      });

      newRoom.on(RoomEvent.ParticipantDisconnected, (participant) => {
        console.log('[livekit] participant disconnected', participant.identity);
      });

      newRoom.on(RoomEvent.Disconnected, (reason) => {
        console.log('[livekit] room disconnected', reason);
        setIsConnected(false);
        setRoom(null);
        setAgentState('disconnected');
      });

      newRoom.on(RoomEvent.TrackSubscribed, (track, publication, participant) => {
        console.log('[livekit] track subscribed', {
          kind: track.kind,
          trackSid: publication?.trackSid || publication?.sid,
          participant: participant.identity,
        });
      });

      newRoom.on(RoomEvent.LocalTrackPublished, (publication, participant) => {
        console.log('[livekit] local track published', {
          kind: publication.kind,
          source: publication.source,
          muted: publication.isMuted,
          participant: participant.identity,
        });
      });

      newRoom.on(RoomEvent.TrackMuted, (publication, participant) => {
        console.log('[livekit] track muted', {
          kind: publication.kind,
          source: publication.source,
          participant: participant.identity,
        });
      });

      newRoom.on(RoomEvent.TrackUnmuted, (publication, participant) => {
        console.log('[livekit] track unmuted', {
          kind: publication.kind,
          source: publication.source,
          participant: participant.identity,
        });
      });

      newRoom.on(RoomEvent.TranscriptionReceived, (segments, participant, publication) => {
        const participantIdentity = participant?.identity || '';
        const role = getParticipantRole(participantIdentity);

        console.log('[livekit] transcription event', {
          participantIdentity,
          role,
          trackSid: publication?.trackSid || publication?.sid,
          segments,
        });

        segments.forEach((segment) => {
          appendTranscription({
            id: segment.id,
            text: segment.text,
            isFinal: segment.final,
            participantIdentity,
            role,
            source: 'livekit-transcription',
          });
        });
      });

      if (typeof newRoom.registerTextStreamHandler === 'function') {
        try {
          newRoom.registerTextStreamHandler(TRANSCRIPTION_TOPIC, async (reader, participantInfo) => {
            const attributes = reader.info?.attributes || {};
            const participantIdentity = participantInfo?.identity || '';
            const segmentId = attributes['lk.segment_id'] || reader.info?.id || `stream-${Date.now()}`;
            const isFinal = isFinalAttribute(attributes['lk.transcription_final']);
            const role = getParticipantRole(participantIdentity);
            let streamedText = '';

            try {
              for await (const chunk of reader) {
                streamedText += chunk;
                appendTranscription({
                  id: segmentId,
                  text: streamedText,
                  isFinal,
                  participantIdentity,
                  role,
                  source: 'livekit-text-stream',
                });
              }
            } catch (streamError) {
              console.error('[livekit] transcription stream read failed', streamError);
            }
          });
        } catch (streamHandlerError) {
          console.warn('[livekit] transcription text-stream handler not registered', streamHandlerError);
        }
      }

      let connected = false;
      let lastConnectError = null;
      let connectedUrl = normalizedUrl;

      for (const candidateUrl of connectCandidates) {
        try {
          await newRoom.connect(candidateUrl, token);
          connected = true;
          connectedUrl = candidateUrl;
          break;
        } catch (candidateError) {
          lastConnectError = candidateError;
          console.warn('[livekit] connect candidate failed', {
            candidateUrl,
            errorName: candidateError?.name,
            errorMessage: candidateError?.message,
          });
        }
      }

      if (!connected) {
        throw lastConnectError || new Error('No LiveKit candidate URL succeeded');
      }

      console.log('[livekit] connected successfully', {
        roomName: newRoom.name,
        roomSid: newRoom.sid,
        connectedUrl,
      });

      setRoom(newRoom);
      setIsConnected(true);
      setAgentState('connecting');
      return newRoom;
    } catch (err) {
      const message = buildConnectErrorMessage(err, normalizedUrl, connectCandidates);
      console.error('[livekit] connect failed', {
        url: normalizedUrl,
        candidates: connectCandidates,
        urlHost: getHostFromUrl(normalizedUrl),
        pageHost: window.location.host,
        errorName: err?.name,
        errorMessage: err?.message,
        stack: err?.stack,
      });
      setError(message);
      throw new Error(message);
    } finally {
      setIsConnecting(false);
    }
  }, [isConnecting]);

  const disconnect = useCallback(() => {
    if (!room) {
      return;
    }

    if (typeof room.unregisterTextStreamHandler === 'function') {
      room.unregisterTextStreamHandler(TRANSCRIPTION_TOPIC);
    }
    room.disconnect();
    setRoom(null);
    setIsConnected(false);
    setAgentState('disconnected');
  }, [room]);

  const logConnectionDetails = useCallback((url, token, roomName) => {
    console.log('[livekit] connection details', {
      url,
      urlHost: getHostFromUrl(url),
      roomName,
      tokenLength: token ? token.length : 0,
    });

    setConnectionDetails({ url, token, roomName });
  }, []);

  const sendChatMessage = useCallback((message) => {
    if (!room || !isConnected) {
      console.error('[livekit] cannot send chat message: not connected');
      return false;
    }

    try {
      const data = {
        type: 'chat',
        message,
        timestamp: new Date().toISOString(),
        sender: 'user',
      };
      const encoder = new TextEncoder();
      const payload = encoder.encode(JSON.stringify(data));
      room.localParticipant.publishData(payload, DataPacket_Kind.RELIABLE);
      return true;
    } catch (publishError) {
      console.error('[livekit] failed to send chat message', publishError);
      return false;
    }
  }, [isConnected, room]);

  const value = {
    room,
    isConnected,
    isConnecting,
    error,
    setError,
    connectionDetails,
    connect,
    disconnect,
    logConnectionDetails,
    transcriptions,
    chatMessages,
    agentState,
    sendChatMessage,
  };

  return <LiveKitContext.Provider value={value}>{children}</LiveKitContext.Provider>;
}

export default LiveKitContext;
