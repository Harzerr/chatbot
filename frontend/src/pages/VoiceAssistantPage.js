import React, { useEffect, useRef, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Container,
  Divider,
  Paper,
  Stack,
  Typography,
} from '@mui/material';
import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded';
import DownloadRoundedIcon from '@mui/icons-material/DownloadRounded';
import MicRoundedIcon from '@mui/icons-material/MicRounded';
import PsychologyAltRoundedIcon from '@mui/icons-material/PsychologyAltRounded';
import QueryStatsRoundedIcon from '@mui/icons-material/QueryStatsRounded';
import RefreshRoundedIcon from '@mui/icons-material/RefreshRounded';
import TipsAndUpdatesRoundedIcon from '@mui/icons-material/TipsAndUpdatesRounded';
import WorkOutlineRoundedIcon from '@mui/icons-material/WorkOutlineRounded';
import { useLocation, useNavigate } from 'react-router-dom';
import VoiceAssistant, { DeviceCheckPanel } from '../components/VoiceAssistant';
import { useLiveKit } from '../contexts/LiveKitContext';
import chatService from '../services/chatService';
import { downloadVoiceInterviewBundle } from '../utils/voiceInterviewExport';

const buildTranscriptTurns = (messages = []) => (
  messages
    .filter((message) => !message.isSystem && String(message.text || '').trim())
    .map((message) => ({
      role: message.role === 'interviewer' ? 'interviewer' : 'candidate',
      text: String(message.text || '').trim(),
      timestamp: message.timestamp || new Date().toISOString(),
    }))
);

const buildTranscriptSignature = (transcript = []) => transcript
  .map((turn) => `${turn.role}:${turn.timestamp || ''}:${turn.text}`)
  .join('\n');

const scoreCardsFromReport = (report) => ([
  { label: '综合得分', value: report?.overall_score ?? '--', tone: '#7dd3fc' },
  { label: '表达清晰度', value: report?.communication_clarity ?? '--', tone: '#34d399' },
  { label: '逻辑结构', value: report?.logical_structure ?? '--', tone: '#fbbf24' },
  { label: '岗位匹配', value: report?.job_match_score ?? '--', tone: '#f472b6' },
]);

const VoiceAssistantPage = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { isConnected, agentState } = useLiveKit();
  const routeInterviewContext = location.state?.interviewContext || {};

  const interviewContext = {
    chatId: routeInterviewContext.chatId || null,
    interviewRole: routeInterviewContext.interviewRole || '通用软件工程师',
    interviewLevel: routeInterviewContext.interviewLevel || '中级',
    interviewType: routeInterviewContext.interviewType || '一面',
    targetCompany: routeInterviewContext.targetCompany || '',
    jdContent: routeInterviewContext.jdContent || '',
  };

  const [conversationMessages, setConversationMessages] = useState([]);
  const [voiceReport, setVoiceReport] = useState(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportError, setReportError] = useState('');
  const [reportGeneratedAt, setReportGeneratedAt] = useState('');
  const autoReportSignatureRef = useRef('');

  const transcriptTurns = buildTranscriptTurns(conversationMessages);
  const transcriptSignature = buildTranscriptSignature(transcriptTurns);
  const candidateAnswerCount = transcriptTurns.filter((turn) => turn.role === 'candidate').length;
  const interviewerTurnCount = transcriptTurns.filter((turn) => turn.role === 'interviewer').length;
  const canAnalyze = transcriptTurns.length >= 4 && candidateAnswerCount > 0;
  const displayAgentState = isConnected
    ? (agentState && agentState !== 'disconnected' ? agentState : 'connecting')
    : 'disconnected';
  const scoreCards = scoreCardsFromReport(voiceReport);

  const requestVoiceReport = async () => {
    if (!canAnalyze) {
      setReportError('请先完成至少一轮语音问答，再生成面试评估。');
      return null;
    }

    setReportLoading(true);
    setReportError('');

    try {
      const response = await chatService.generateVoiceInterviewReport({
        chat_id: interviewContext.chatId,
        interview_role: interviewContext.interviewRole,
        interview_level: interviewContext.interviewLevel,
        interview_type: interviewContext.interviewType,
        target_company: interviewContext.targetCompany,
        jd_content: interviewContext.jdContent,
        transcript: transcriptTurns,
      });
      setVoiceReport(response);
      setReportGeneratedAt(new Date().toISOString());
      return response;
    } catch (error) {
      const detail = error?.response?.data?.detail;
      setReportError(detail || error?.message || '生成语音面试评估失败，请稍后重试。');
      return null;
    } finally {
      setReportLoading(false);
    }
  };

  useEffect(() => {
    if (isConnected || !canAnalyze || !transcriptSignature) {
      return;
    }
    if (autoReportSignatureRef.current === transcriptSignature) {
      return;
    }

    autoReportSignatureRef.current = transcriptSignature;
    const runAutoAnalysis = async () => {
      setReportLoading(true);
      setReportError('');

      try {
        const response = await chatService.generateVoiceInterviewReport({
          chat_id: interviewContext.chatId,
          interview_role: interviewContext.interviewRole,
          interview_level: interviewContext.interviewLevel,
          interview_type: interviewContext.interviewType,
          target_company: interviewContext.targetCompany,
          jd_content: interviewContext.jdContent,
          transcript: transcriptTurns,
        });
        setVoiceReport(response);
        setReportGeneratedAt(new Date().toISOString());
      } catch (error) {
        const detail = error?.response?.data?.detail;
        setReportError(detail || error?.message || '生成语音面试评估失败，请稍后重试。');
      } finally {
        setReportLoading(false);
      }
    };
    runAutoAnalysis();
  }, [isConnected, canAnalyze, transcriptSignature, interviewContext.chatId, interviewContext.interviewLevel, interviewContext.interviewRole, interviewContext.interviewType, interviewContext.jdContent, interviewContext.targetCompany, transcriptTurns]);

  useEffect(() => {
    if (!transcriptSignature) {
      setVoiceReport(null);
      setReportError('');
      setReportGeneratedAt('');
      autoReportSignatureRef.current = '';
    }
  }, [transcriptSignature]);

  const handleManualRefresh = async () => {
    if (transcriptSignature) {
      autoReportSignatureRef.current = transcriptSignature;
    }
    await requestVoiceReport();
  };

  const handleExport = () => {
    downloadVoiceInterviewBundle({
      interviewContext,
      transcript: transcriptTurns,
      report: voiceReport,
    });
  };

  const renderTranscriptPreview = () => {
    if (!transcriptTurns.length) {
      return (
        <Typography variant="body2" color="text.secondary">
          开始语音面试后，这里会同步显示最近的对话记录，并在结束后自动生成整场面试建议。
        </Typography>
      );
    }

    return (
      <Stack spacing={1.2}>
        {transcriptTurns.slice(-6).map((turn, index) => (
          <Box
            key={`${turn.role}-${turn.timestamp || index}-${index}`}
            sx={{
              p: 1.4,
              borderRadius: '10px',
              bgcolor: turn.role === 'candidate' ? 'rgba(125,211,252,0.08)' : 'rgba(52,211,153,0.08)',
              border: `1px solid ${turn.role === 'candidate' ? 'rgba(125,211,252,0.18)' : 'rgba(52,211,153,0.18)'}`,
            }}
          >
            <Typography variant="caption" sx={{ color: '#e2e8f0', display: 'block', mb: 0.5 }}>
              {turn.role === 'candidate' ? '候选人' : '面试官'}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: 'pre-wrap' }}>
              {turn.text}
            </Typography>
          </Box>
        ))}
      </Stack>
    );
  };

  return (
    <Container maxWidth="xl" sx={{ py: 4 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 2, mb: 3 }}>
        <Box>
          <Button
            startIcon={<ArrowBackRoundedIcon />}
            onClick={() => navigate('/chat')}
            sx={{ mb: 2, color: '#cbd5e1' }}
          >
            返回面试控制台
          </Button>
          <Typography variant="h4" component="h1" gutterBottom>
            语音面试房间
          </Typography>
          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
            <Chip
              icon={<WorkOutlineRoundedIcon />}
              label={interviewContext.interviewRole}
              sx={{ bgcolor: 'rgba(125,211,252,0.10)', color: '#7dd3fc' }}
            />
            <Chip
              icon={<QueryStatsRoundedIcon />}
              label={`${interviewContext.interviewLevel} · ${interviewContext.interviewType}`}
              sx={{ bgcolor: 'rgba(245,158,11,0.10)', color: '#fbbf24' }}
            />
            <Chip
              icon={<MicRoundedIcon />}
              label={isConnected ? '语音面试进行中' : transcriptTurns.length ? '已完成，可复盘' : '等待开始'}
              sx={{ bgcolor: 'rgba(52,211,153,0.10)', color: '#86efac' }}
            />
          </Stack>
        </Box>
      </Box>

      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: {
            xs: '1fr',
            lg: 'minmax(260px, 0.74fr) minmax(520px, 1.55fr) minmax(340px, 0.96fr)',
          },
          alignItems: 'stretch',
          gap: 3,
        }}
      >
        <DeviceCheckPanel />

        <Box
          sx={{
            display: 'flex',
            flexDirection: 'column',
            minHeight: { xs: 620, lg: 'calc(100vh - 220px)' },
          }}
        >
          <VoiceAssistant
            interviewContext={interviewContext}
            onMessagesChange={setConversationMessages}
          />
        </Box>

        <Paper
          elevation={0}
          sx={{
            p: 3,
            minHeight: { lg: 'calc(100vh - 220px)' },
            borderRadius: '8px',
            background: 'linear-gradient(180deg, rgba(13,23,40,0.9) 0%, rgba(8,15,28,0.98) 100%)',
            border: '1px solid rgba(148,163,184,0.12)',
            display: 'flex',
            flexDirection: 'column',
            gap: 2.5,
          }}
        >
          <Box>
            <Typography variant="h6" sx={{ mt: 0.5 }}>
              模拟面试评估
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
              右侧会基于本场语音转写记录调用 LLM 做整场表现分析，生成优势、改进点和后续建议。
            </Typography>
          </Box>

          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
            <Chip
              icon={<MicRoundedIcon />}
              label={`语音记录 ${transcriptTurns.length} 条`}
              sx={{ bgcolor: 'rgba(148,163,184,0.08)', color: '#cbd5e1' }}
            />
            <Chip
              icon={<PsychologyAltRoundedIcon />}
              label={`候选人作答 ${candidateAnswerCount} 轮`}
              sx={{ bgcolor: 'rgba(125,211,252,0.10)', color: '#7dd3fc' }}
            />
            <Chip
              icon={<QueryStatsRoundedIcon />}
              label={`追问/发问 ${interviewerTurnCount} 次`}
              sx={{ bgcolor: 'rgba(245,158,11,0.10)', color: '#fbbf24' }}
            />
          </Stack>

          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.2}>
            <Button
              variant="contained"
              startIcon={reportLoading ? <CircularProgress size={18} color="inherit" /> : <TipsAndUpdatesRoundedIcon />}
              onClick={handleManualRefresh}
              disabled={reportLoading}
              sx={{ flex: 1 }}
            >
              {voiceReport ? '刷新面试建议' : '生成面试建议'}
            </Button>
            <Button
              variant="outlined"
              startIcon={<DownloadRoundedIcon />}
              onClick={handleExport}
              disabled={!transcriptTurns.length}
              sx={{
                flex: 1,
                borderColor: 'rgba(148,163,184,0.45)',
                color: '#dbeafe',
                '&:hover': { borderColor: '#93c5fd', backgroundColor: 'rgba(37,99,235,0.12)' },
              }}
            >
              导出语音记录与评价
            </Button>
          </Stack>

          {reportError && <Alert severity="warning">{reportError}</Alert>}

          <Box
            sx={{
              p: 2,
              borderRadius: '10px',
              bgcolor: 'rgba(15,23,42,0.58)',
              border: '1px solid rgba(148,163,184,0.10)',
            }}
          >
            <Typography variant="subtitle2" sx={{ color: '#f8fafc', mb: 1 }}>
              当前状态
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {isConnected
                ? `语音面试进行中，Agent 当前状态：${displayAgentState}。`
                : transcriptTurns.length
                  ? '语音会话已结束，你可以查看建议，或继续导出本场语音记录与评价。'
                  : '请先完成设备检测，然后开启语音面试。'}
            </Typography>
          </Box>

          {reportLoading ? (
            <Box
              sx={{
                minHeight: 180,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 1.5,
              }}
            >
              <CircularProgress />
              <Typography variant="body2" color="text.secondary">
                正在分析整场语音面试表现...
              </Typography>
            </Box>
          ) : voiceReport ? (
            <>
              <Box
                sx={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
                  gap: 1.2,
                }}
              >
                {scoreCards.map((item) => (
                  <Box
                    key={item.label}
                    sx={{
                      p: 1.6,
                      borderRadius: '12px',
                      bgcolor: 'rgba(15,23,42,0.62)',
                      border: '1px solid rgba(148,163,184,0.12)',
                    }}
                  >
                    <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block' }}>
                      {item.label}
                    </Typography>
                    <Typography variant="h6" sx={{ color: item.tone, mt: 0.6 }}>
                      {item.value}
                    </Typography>
                  </Box>
                ))}
              </Box>

              <Box>
                <Typography variant="subtitle2" sx={{ color: '#f8fafc', mb: 1 }}>
                  面试总结
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: 'pre-wrap', lineHeight: 1.8 }}>
                  {voiceReport.summary}
                </Typography>
              </Box>

              <Box>
                <Typography variant="subtitle2" sx={{ color: '#f8fafc', mb: 1 }}>
                  内容分析
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: 'pre-wrap', lineHeight: 1.8 }}>
                  {voiceReport.content_analysis}
                </Typography>
              </Box>

              <Box>
                <Typography variant="subtitle2" sx={{ color: '#f8fafc', mb: 1 }}>
                  优势亮点
                </Typography>
                <Stack spacing={1}>
                  {voiceReport.strengths?.length ? voiceReport.strengths.map((item, index) => (
                    <Chip
                      key={`${item}-${index}`}
                      label={item}
                      sx={{ justifyContent: 'flex-start', borderRadius: '8px', bgcolor: 'rgba(52,211,153,0.12)', color: '#bbf7d0' }}
                    />
                  )) : (
                    <Typography variant="body2" color="text.secondary">暂无明显优势项</Typography>
                  )}
                </Stack>
              </Box>

              <Box>
                <Typography variant="subtitle2" sx={{ color: '#f8fafc', mb: 1 }}>
                  待改进项
                </Typography>
                <Stack spacing={1}>
                  {voiceReport.improvement_areas?.length ? voiceReport.improvement_areas.map((item, index) => (
                    <Chip
                      key={`${item}-${index}`}
                      label={item}
                      sx={{ justifyContent: 'flex-start', borderRadius: '8px', bgcolor: 'rgba(248,113,113,0.10)', color: '#fecaca' }}
                    />
                  )) : (
                    <Typography variant="body2" color="text.secondary">暂无待改进项</Typography>
                  )}
                </Stack>
              </Box>

              <Box
                sx={{
                  p: 2,
                  borderRadius: '8px',
                  bgcolor: 'rgba(125,211,252,0.06)',
                  border: '1px solid rgba(125,211,252,0.08)',
                }}
              >
                <Typography variant="subtitle2" sx={{ color: '#f8fafc', mb: 0.8 }}>
                  面试建议
                </Typography>
                <Stack spacing={1}>
                  {voiceReport.recommendations?.length ? voiceReport.recommendations.map((item, index) => (
                    <Typography key={`${item}-${index}`} variant="body2" color="text.secondary">
                      {index + 1}. {item}
                    </Typography>
                  )) : (
                    <Typography variant="body2" color="text.secondary">
                      暂无建议
                    </Typography>
                  )}
                </Stack>
              </Box>
            </>
          ) : (
            <Box
              sx={{
                p: 2,
                borderRadius: '10px',
                bgcolor: 'rgba(148,163,184,0.08)',
                border: '1px dashed rgba(148,163,184,0.18)',
              }}
            >
              <Typography variant="body2" color="text.secondary">
                完成至少一轮语音问答后，系统会根据你的转写记录生成面试总结、薄弱点和提升建议。
              </Typography>
            </Box>
          )}

          <Divider sx={{ borderColor: 'rgba(148,163,184,0.10)' }} />

          <Box>
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
              <Typography variant="subtitle2" sx={{ color: '#f8fafc' }}>
                最近语音对话记录
              </Typography>
              {voiceReport && reportGeneratedAt && (
                <Button
                  size="small"
                  startIcon={<RefreshRoundedIcon />}
                  onClick={handleManualRefresh}
                  disabled={reportLoading}
                >
                  重新分析
                </Button>
              )}
            </Box>
            <Box sx={{ maxHeight: 260, overflowY: 'auto', pr: 0.5 }}>
              {renderTranscriptPreview()}
            </Box>
          </Box>
        </Paper>
      </Box>
    </Container>
  );
};

export default VoiceAssistantPage;
