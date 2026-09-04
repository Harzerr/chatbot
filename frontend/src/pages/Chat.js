import React, { useState, useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  Box,
  Alert,
  Drawer,
  List,
  ListItem,
  ListItemButton,
  Typography,
  IconButton,
  Divider,
  AppBar,
  Toolbar,
  Button,
  CircularProgress,
  useMediaQuery,
  useTheme,
  Chip,
  Paper,
  Stack,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  MenuItem,
  Tooltip,
} from '@mui/material';
import MenuIcon from '@mui/icons-material/Menu';
import AddIcon from '@mui/icons-material/Add';
import LogoutIcon from '@mui/icons-material/Logout';
import MicIcon from '@mui/icons-material/Mic';
import ScheduleRoundedIcon from '@mui/icons-material/ScheduleRounded';
import TrackChangesRoundedIcon from '@mui/icons-material/TrackChangesRounded';
import WorkOutlineRoundedIcon from '@mui/icons-material/WorkOutlineRounded';
import AutoGraphRoundedIcon from '@mui/icons-material/AutoGraphRounded';
import AssignmentTurnedInRoundedIcon from '@mui/icons-material/AssignmentTurnedInRounded';
import TipsAndUpdatesRoundedIcon from '@mui/icons-material/TipsAndUpdatesRounded';
import MenuBookRoundedIcon from '@mui/icons-material/MenuBookRounded';
import LightbulbRoundedIcon from '@mui/icons-material/LightbulbRounded';
import AccountCircleRoundedIcon from '@mui/icons-material/AccountCircleRounded';
import PauseCircleOutlineRoundedIcon from '@mui/icons-material/PauseCircleOutlineRounded';
import PlayCircleOutlineRoundedIcon from '@mui/icons-material/PlayCircleOutlineRounded';
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded';
import { useAuth } from '../contexts/AuthContext';
import chatService from '../services/chatService';
import careerService from '../services/careerService';
import streamingService from '../services/streamingService';
import MessageBubble from '../components/MessageBubble';
import ChatInput from '../components/ChatInput';

const drawerWidth = 320;
const roleOptions = ['Java后端工程师', 'C++开发工程师', '测试工程师', 'Web前端工程师', 'Python算法工程师', '通用软件工程师'];
const levelOptions = ['初级', '中级', '高级', '资深进阶'];
const interviewTypeOptions = ['一面', '二面', '三面', 'HR面'];
const interviewQuestionLimits = {
  一面: 10,
  二面: 10,
  三面: 10,
  HR面: 10,
};
const interviewTimeProfiles = {
  一面: { minutesPerQuestion: 5, bufferMinutes: 5 },
  二面: { minutesPerQuestion: 6, bufferMinutes: 6 },
  三面: { minutesPerQuestion: 6, bufferMinutes: 8 },
  HR面: { minutesPerQuestion: 5, bufferMinutes: 5 },
};

const getInterviewQuestionLimit = (interviewType = '一面') => interviewQuestionLimits[interviewType] || 10;
const getEstimatedInterviewMinutes = (interviewType = '一面') => {
  const profile = interviewTimeProfiles[interviewType] || interviewTimeProfiles.一面;
  return getInterviewQuestionLimit(interviewType) * profile.minutesPerQuestion + profile.bufferMinutes;
};
const buildInterviewJdContext = (job) => {
  const normalized = job?.normalized || {};
  const lines = [
    `职位：${job?.title || ''}`,
    job?.company ? `公司：${job.company}` : '',
    Array.isArray(normalized.required_skills) && normalized.required_skills.length ? `核心要求：${normalized.required_skills.join('；')}` : '',
    Array.isArray(normalized.responsibilities) && normalized.responsibilities.length ? `工作职责：${normalized.responsibilities.join('；')}` : '',
    Array.isArray(normalized.preferred_skills) && normalized.preferred_skills.length ? `加分项：${normalized.preferred_skills.join('；')}` : '',
    job?.raw_content ? `JD 原文：\n${job.raw_content}` : '',
  ];
  return lines.filter(Boolean).join('\n\n');
};
const MANUAL_FINISH_COMMAND = '__SYSTEM_END_INTERVIEW_AND_EXPORT_REPORT__';

const isManualFinishCommand = (content = '') => content === MANUAL_FINISH_COMMAND;

const getMessageContent = (message = {}) => (
  message.content || message.assistant_message || message.user_message || ''
);

const normalizeText = (value = '') => String(value || '').replace(/\s+/g, '');

const interviewEndMarkers = [
  '本场面试已结束',
  '本次面试已结束',
  '本场面试结束',
  '本次面试结束',
  '面试已结束',
  '面试到此结束',
  '本场面试到此结束',
  '本次面试到此结束',
  '面试环节结束',
];

const includesInterviewEndMarker = (content = '') => {
  const normalized = normalizeText(content);
  return interviewEndMarkers.some((marker) => normalized.includes(marker));
};

const nonAnswerMarkers = [
  '不知道', '不清楚', '不太清楚', '不了解', '不太知道', '没接触过', '没有接触过', '没做过', '没有做过',
  '不熟悉', '不太会', '不会', '答不上来', '无法回答', '不记得', '想不起来',
  '没有相关经验', '无相关经验',
];

const isCountedInterviewAnswer = (message = {}) => {
  const content = normalizeText(message.user_message || '');
  if (message.answer_counted === false) return false;
  if (!content || isManualFinishCommand(content) || ['开始面试', '开始', '继续', '开始吧', '可以开始了', '继续面试'].includes(content)) {
    return false;
  }
  return !nonAnswerMarkers.some((marker) => content.includes(marker));
};

const getCompletedAnswerCount = (chatMessages = []) => chatMessages.filter(isCountedInterviewAnswer).length;

const isFinishedInterviewStatus = (status = '') => {
  const normalized = normalizeText(status).toLowerCase();
  if (!normalized) return false;
  return [
    '已完成',
    '已结束',
    '待复盘',
    'completed',
    'complete',
    'finished',
    'done',
    'closed',
  ].some((marker) => normalized.includes(marker));
};

const looksLikeCodingQuestion = (content = '') => {
  const lower = content.toLowerCase();
  return (
    lower.includes('代码题')
    || lower.includes('手撕代码')
    || lower.includes('实现“')
    || lower.includes('实现"')
    || lower.includes('请你实现')
    || lower.includes('leetcode')
    || lower.includes('时间复杂度')
    || lower.includes('空间复杂度')
  );
};

const hasInterviewEnded = (messageList = []) => messageList.some((message) => {
  if (isManualFinishCommand(message.user_message || message.content || '')) {
    return true;
  }
  const isAssistantMessage = message.role === 'assistant' || !!message.assistant_message;
  return isAssistantMessage && includesInterviewEndMarker(getMessageContent(message));
});

const getMessageTimestamp = (message = {}) => {
  const value = message.timestamp || message.created_at || message.updated_at;
  const timestamp = value ? new Date(value).getTime() : Number.NaN;
  return Number.isNaN(timestamp) ? null : timestamp;
};

const getInterviewStartedAt = (chat = {}) => {
  const messageTimes = (chat.messages || [])
    .map(getMessageTimestamp)
    .filter(Boolean);
  const firstMessageTime = messageTimes.length ? Math.min(...messageTimes) : null;
  return chat.startedAt || (firstMessageTime ? new Date(firstMessageTime).toISOString() : chat.timestamp);
};

const getInterviewEndedAt = (chat = {}) => {
  const messageTimes = (chat.messages || [])
    .map(getMessageTimestamp)
    .filter(Boolean);
  const lastMessageTime = messageTimes.length ? Math.max(...messageTimes) : null;
  const fallbackEndedAt = lastMessageTime ? new Date(lastMessageTime).toISOString() : chat.timestamp || null;

  if (chat.endedAt) {
    return chat.endedAt;
  }
  if (hasInterviewEnded(chat.messages || []) || isFinishedInterviewStatus(chat.status)) {
    return fallbackEndedAt;
  }

  return null;
};

const getElapsedInterviewMinutes = (
  startedAt,
  endedAt = null,
  fallbackNow = Date.now(),
  pausedSeconds = 0,
  pausedAt = null,
) => {
  const startTime = startedAt ? new Date(startedAt).getTime() : Number.NaN;
  const pausedTime = pausedAt ? new Date(pausedAt).getTime() : Number.NaN;
  const endTime = endedAt ? new Date(endedAt).getTime() : (Number.isNaN(pausedTime) ? fallbackNow : pausedTime);

  if (Number.isNaN(startTime) || Number.isNaN(endTime) || endTime <= startTime) {
    return 0;
  }

  const activeMilliseconds = Math.max(0, endTime - startTime - (Number(pausedSeconds) || 0) * 1000);
  return Math.max(1, Math.ceil(activeMilliseconds / 60000));
};

const formatMinuteAmount = (minutes) => {
  if (!minutes) return '< 1 分钟';
  return `${minutes} 分钟`;
};

const buildInterviewTimeCopy = (meta = {}, now = Date.now()) => {
  const estimatedMinutes = meta.estimatedMinutes || getEstimatedInterviewMinutes(meta.interviewType);
  const elapsedMinutes = getElapsedInterviewMinutes(
    meta.startedAt,
    meta.endedAt,
    now,
    meta.pausedSeconds,
    meta.pausedAt,
  );

  if (meta.isFinished || meta.status === '已完成' || meta.status === '待复盘') {
    return {
      short: `用时 ${formatMinuteAmount(elapsedMinutes)}`,
      detail: `实际用时 ${formatMinuteAmount(elapsedMinutes)} · 预计 ${estimatedMinutes} 分钟`,
    };
  }

  if (meta.status === '待开始' || meta.status === '新会话') {
    return {
      short: `预计 ${estimatedMinutes} 分钟`,
      detail: `预计 ${estimatedMinutes} 分钟 · ${getInterviewQuestionLimit(meta.interviewType)} 题节奏`,
    };
  }

  return meta.isPaused
    ? {
      short: `已暂停 · ${formatMinuteAmount(elapsedMinutes)}`,
      detail: `计时已暂停 · 已用 ${formatMinuteAmount(elapsedMinutes)}`,
    }
    : {
      short: `已用 ${formatMinuteAmount(elapsedMinutes)}`,
      detail: `已用 ${formatMinuteAmount(elapsedMinutes)} · 预计 ${estimatedMinutes} 分钟`,
    };
};

const hasPendingEvaluations = (reportData = {}) => (
  (reportData.interview_questions || []).some((item) => (
    item.answer_counted !== false
      && String(item.candidate_answer || '').trim()
      && (
        item.evaluation_status === 'queued'
        || item.evaluation_status === 'processing'
        || (!item.evaluation && item.evaluation_status !== 'failed')
      )
  ))
);

const getEffectiveAnswerCount = (reportData = {}) => {
  const scoredCount = Number(reportData?.total_answers || 0);
  const qaCount = Array.isArray(reportData?.interview_questions)
    ? reportData.interview_questions.filter((item) => (
      item?.answer_counted !== false && String(item?.candidate_answer || '').trim()
    )).length
    : 0;
  return Math.max(scoredCount, qaCount);
};

const REPORT_SCORE_FIELDS = [
  { key: 'technical_accuracy', label: '技术准确性', icon: AssignmentTurnedInRoundedIcon },
  { key: 'knowledge_depth', label: '知识深度', icon: AutoGraphRoundedIcon },
  { key: 'communication_clarity', label: '表达清晰度', icon: TipsAndUpdatesRoundedIcon },
  { key: 'logical_structure', label: '逻辑结构', icon: AssignmentTurnedInRoundedIcon },
  { key: 'problem_solving', label: '问题解决能力', icon: AutoGraphRoundedIcon },
  { key: 'job_match_score', label: '岗位匹配度', icon: TrackChangesRoundedIcon },
];

const getAvailableReportScores = (evaluation = {}) => {
  const overallScore = Number(evaluation.overall_score);
  const dimensionValues = REPORT_SCORE_FIELDS.map(({ key }) => Number(evaluation[key]));
  const legacyDefaultBlock = Number.isFinite(overallScore)
    && overallScore > 0
    && dimensionValues.every((value) => value === 0);

  return REPORT_SCORE_FIELDS.filter(({ key }) => {
    const value = evaluation[key];
    return value !== null
      && value !== undefined
      && value !== ''
      && Number.isFinite(Number(value))
      && !legacyDefaultBlock;
  });
};

const getLatestEvaluation = (messages = []) => (
  [...messages]
    .sort((a, b) => (getMessageTimestamp(b) || 0) - (getMessageTimestamp(a) || 0))
    .find((message) => message.evaluation)?.evaluation || null
);

const deriveInterviewMeta = (chat) => {
  const latestEvaluation = getLatestEvaluation(chat.messages);

  if (chat.interviewRole || chat.interviewLevel || chat.interviewType) {
    const completedAnswerCount = getCompletedAnswerCount(chat.messages);
    const interviewType = chat.interviewType || '一面';
    const startedAt = getInterviewStartedAt(chat);
    const endedAt = getInterviewEndedAt(chat);
    const isFinished = !!endedAt;
    const questionCount = Math.max(1, isFinished ? completedAnswerCount : completedAnswerCount + 1);
    const status = isFinished ? '已完成' : chat.status || '进行中';
    const estimatedMinutes = getEstimatedInterviewMinutes(interviewType);
    return {
      role: chat.interviewRole || '通用软件工程师',
      level: chat.interviewLevel || '中级',
      interviewType,
      targetCompany: chat.targetCompany || '',
      score: latestEvaluation?.overall_score ?? null,
      status,
      interviewStatus: chat.interviewStatus || 'active',
      pausedAt: chat.interviewPausedAt || null,
      pausedSeconds: Number(chat.interviewPausedSeconds) || 0,
      startedAt,
      endedAt,
      isFinished,
      estimatedMinutes,
      duration: chat.duration || `预计 ${estimatedMinutes} 分钟`,
      questionCount,
      targetQuestions: getInterviewQuestionLimit(interviewType),
      title: `${chat.interviewRole || '通用软件工程师'} 面试`,
    };
  }

  const seed = chat.id.split('').reduce((sum, char) => sum + char.charCodeAt(0), 0);
  const tracks = ['Java后端工程师', 'C++开发工程师', '测试工程师', 'Web前端工程师', 'Python算法工程师'];
  const levels = ['中级', '高级', '资深进阶'];
  const interviewTypes = ['一面', '二面', '三面', 'HR面'];
  const statuses = ['进行中', '待复盘', '已完成'];
  const role = tracks[seed % tracks.length];
  const level = levels[seed % levels.length];
  const interviewType = interviewTypes[seed % interviewTypes.length];
  const completedAnswerCount = getCompletedAnswerCount(chat.messages);
  const targetQuestions = getInterviewQuestionLimit(interviewType);
  const isFinished = hasInterviewEnded(chat.messages || []);
  const questionCount = Math.max(1, isFinished ? completedAnswerCount : completedAnswerCount + 1);
  const status = isFinished ? '已完成' : statuses[questionCount % statuses.length];
  const startedAt = getInterviewStartedAt(chat);
  const endedAt = getInterviewEndedAt(chat);
  const estimatedMinutes = getEstimatedInterviewMinutes(interviewType);
  const duration = `预计 ${estimatedMinutes} 分钟`;

  return {
    role,
    level,
    interviewType,
    score: latestEvaluation?.overall_score ?? null,
    status,
    interviewStatus: chat.interviewStatus || 'active',
    pausedAt: chat.interviewPausedAt || null,
    pausedSeconds: Number(chat.interviewPausedSeconds) || 0,
    startedAt,
    endedAt,
    isFinished,
    estimatedMinutes,
    duration,
    questionCount,
    targetQuestions,
    title: `${role} 面试`,
  };
};

const Chat = () => {
  const [chats, setChats] = useState([]);
  const [currentChat, setCurrentChat] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [chatLoading, setChatLoading] = useState(false);
  const [error, setError] = useState(null);
  const [streamingMessage, setStreamingMessage] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [latestCodeExecution, setLatestCodeExecution] = useState(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [setupDialogOpen, setSetupDialogOpen] = useState(false);
  const [resumePromptOpen, setResumePromptOpen] = useState(false);
  const [report, setReport] = useState(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [finishExportLoading, setFinishExportLoading] = useState(false);
  const [sessionActionLoading, setSessionActionLoading] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [finishRequestedAt, setFinishRequestedAt] = useState(null);
  const [timeNow, setTimeNow] = useState(() => Date.now());
  const [interviewSetup, setInterviewSetup] = useState({
    interviewRole: 'Web前端工程师',
    interviewLevel: '中级',
    interviewType: '一面',
    targetCompany: '',
    jdContent: '',
    jobPostingId: '',
  });
  const [interviewJobs, setInterviewJobs] = useState([]);
  const [interviewJobsLoading, setInterviewJobsLoading] = useState(false);
  const [interviewJobsError, setInterviewJobsError] = useState('');
  const [retryingEvaluationId, setRetryingEvaluationId] = useState(null);
  const [evaluationExportNotice, setEvaluationExportNotice] = useState('');

  const isInterviewFinished = (messageList = messages) => {
    return hasInterviewEnded(messageList);
  };

  const messagesEndRef = useRef(null);
  const currentChatIdRef = useRef(null);
  const messageRequestIdRef = useRef(0);
  const reportRequestIdRef = useRef(0);
  const reportInFlightRef = useRef(false);
  const { logout, currentUser } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('lg'));

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingMessage]);

  useEffect(() => {
    const chatId = currentChat?.id;
    const pendingEvaluation = currentChat?.messages?.some((message) => (
      message.evaluation_status === 'queued' || message.evaluation_status === 'processing'
    ));
    if (!chatId || isStreaming || !pendingEvaluation) return undefined;

    const timer = window.setInterval(async () => {
      await fetchMessages(chatId, { silent: true, loadReport: true });
    }, 1500);
    return () => window.clearInterval(timer);
  }, [currentChat?.id, currentChat?.messages, isStreaming]);

  useEffect(() => {
    currentChatIdRef.current = currentChat?.id || null;
  }, [currentChat?.id]);

  useEffect(() => {
    fetchChats();
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setTimeNow(Date.now());
    }, 30000);

    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!currentUser?.target_role) return;

    setInterviewSetup((prev) => ({
      ...prev,
      interviewRole: prev.jobPostingId ? prev.interviewRole : currentUser.target_role,
    }));
  }, [currentUser]);

  useEffect(() => {
    if (!setupDialogOpen) return;
    let disposed = false;
    setInterviewJobsLoading(true);
    setInterviewJobsError('');
    careerService.listJobs()
      .then((jobs) => {
        if (!disposed) setInterviewJobs(Array.isArray(jobs) ? jobs : []);
      })
      .catch(() => {
        if (!disposed) setInterviewJobsError('职位库加载失败，仍可手工填写 JD。');
      })
      .finally(() => {
        if (!disposed) setInterviewJobsLoading(false);
      });
    return () => { disposed = true; };
  }, [setupDialogOpen]);

  useEffect(() => {
    const interviewJobId = location.state?.interviewJobId;
    if (!interviewJobId) return;
    if (!setupDialogOpen) {
      if (currentUser?.has_resume) setSetupDialogOpen(true);
      else setResumePromptOpen(true);
      return;
    }
    if (interviewJobsLoading) return;
    const job = interviewJobs.find((item) => String(item.id) === String(interviewJobId));
    if (!job) return;
    setInterviewSetup((prev) => ({
      ...prev,
      jobPostingId: String(job.id),
      interviewRole: job.title || prev.interviewRole,
      targetCompany: job.company || prev.targetCompany,
      jdContent: buildInterviewJdContext(job) || prev.jdContent,
    }));
    if (currentUser?.has_resume) setSetupDialogOpen(true);
    else setResumePromptOpen(true);
    navigate(location.pathname, { replace: true, state: {} });
  }, [currentUser?.has_resume, interviewJobs, interviewJobsLoading, location.pathname, location.state, navigate]);

  const clearReportState = () => {
    reportRequestIdRef.current += 1;
    setReportLoading(false);
    setReport(null);
    setEvaluationExportNotice('');
  };

  const fetchInterviewReport = async (chatId, options = {}) => {
    const { rethrow = false, partial = false, silent = false } = options;
    if (silent && reportInFlightRef.current) return null;
    const requestId = reportRequestIdRef.current + 1;
    reportRequestIdRef.current = requestId;
    reportInFlightRef.current = true;
    if (!silent) setReportLoading(true);
    try {
      const response = await chatService.getInterviewReport(chatId, { partial });
      if (requestId !== reportRequestIdRef.current) {
        return null;
      }
      if (!currentChatIdRef.current || currentChatIdRef.current === chatId) {
        setReport(response);
        const pending = hasPendingEvaluations(response);
        setEvaluationExportNotice(pending ? '本场评估仍在处理中，请完成后再导出 PDF。' : '');
      }
      return response;
    } catch (reportError) {
      console.error('Error fetching interview report:', reportError);
      if (requestId === reportRequestIdRef.current && (!currentChatIdRef.current || currentChatIdRef.current === chatId)) {
        setReport(null);
      }
      if (rethrow) {
        throw reportError;
      }
      return null;
    } finally {
      if (requestId === reportRequestIdRef.current && !silent) {
        setReportLoading(false);
      }
      reportInFlightRef.current = false;
    }
  };

  const fetchChats = async (options = {}) => {
    const { silent = false } = options;
    if (!silent) {
      setLoading(true);
      setError(null);
    }

    try {
      const response = await chatService.getUserChats();
      const chatGroups = {};

      response.messages.forEach((msg) => {
        if (!chatGroups[msg.chat_id]) {
          chatGroups[msg.chat_id] = [];
        }
        chatGroups[msg.chat_id].push(msg);
      });

      const chatList = Object.entries(chatGroups).map(([chatId, groupedMessages]) => {
        const sortedMessages = [...groupedMessages].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
        const latestMessage = sortedMessages[0];
        const baseChat = {
          id: chatId,
          timestamp: latestMessage.timestamp,
          messages: sortedMessages,
          preview: isManualFinishCommand(latestMessage.user_message) ? latestMessage.assistant_message : latestMessage.user_message,
          interviewRole: latestMessage.interview_role,
          interviewLevel: latestMessage.interview_level,
          interviewType: latestMessage.interview_type,
          targetCompany: latestMessage.target_company,
          jdContent: latestMessage.jd_content,
          interviewStatus: latestMessage.interview_status || 'active',
          interviewPausedAt: latestMessage.interview_paused_at || null,
          interviewPausedSeconds: Number(latestMessage.interview_paused_seconds) || 0,
        };
        const meta = deriveInterviewMeta(baseChat);
        return { ...baseChat, ...meta };
      });

      const sortedChats = chatList.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
      setChats(sortedChats);
      setCurrentChat((prev) => {
        if (!prev) return prev;
        return sortedChats.find((chat) => chat.id === prev.id) || null;
      });

      if (sortedChats.length > 0 && !currentChat) {
        handleSelectChat(sortedChats[0].id, sortedChats);
      }
    } catch (err) {
      console.error('Error fetching chats:', err);
      if (!silent) setError('加载面试会话失败，请稍后重试。');
    } finally {
      if (!silent) setLoading(false);
    }
  };

  const formatChatMessages = (chatMessages = []) => [...chatMessages]
    .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp))
    .flatMap((msg) => {
      const formattedThread = [];

      if (!isManualFinishCommand(msg.user_message)) {
        formattedThread.push({
          id: msg.id,
          content: msg.user_message,
          role: 'user',
          timestamp: msg.timestamp,
              evaluation: msg.evaluation,
              evaluationStatus: msg.evaluation_status,
              evaluationError: msg.evaluation_error,
              answerCounted: msg.answer_counted,
        });
      }

      if (msg.assistant_message) {
        formattedThread.push({
          id: `${msg.id}-response`,
          content: msg.assistant_message,
          role: 'assistant',
          timestamp: msg.timestamp,
        });
      }

      return formattedThread;
    })
    .filter((message, index, all) => (
      message.role !== 'assistant'
      || index === 0
      || all[index - 1].role !== 'assistant'
      || all[index - 1].content !== message.content
    ));

  const fetchMessages = async (chatId, options = {}) => {
    const { silent = false, loadReport = !silent } = options;
    const requestId = messageRequestIdRef.current + 1;
    messageRequestIdRef.current = requestId;
    if (!silent) setChatLoading(true);
    if (!silent) {
      setError(null);
      clearReportState();
    }

    try {
      const response = await chatService.getChatById(chatId);
      if (requestId !== messageRequestIdRef.current || currentChatIdRef.current !== chatId) return;

      const formattedMessages = formatChatMessages(response.messages);

      setMessages(formattedMessages);
      setCurrentChat((prev) => {
        if (!prev || prev.id !== chatId) return prev;
        const updatedChat = { ...prev, messages: response.messages };
        return { ...updatedChat, ...deriveInterviewMeta(updatedChat) };
      });
      if (loadReport) {
        const finished = formattedMessages.some(
          (message) => message.role === 'assistant' && includesInterviewEndMarker(message.content),
        );
        fetchInterviewReport(chatId, { partial: !finished, silent });
      }
    } catch (err) {
      console.error(`Error fetching messages for chat ${chatId}:`, err);
      if (!silent) setError('加载面试记录失败，请稍后重试。');
    } finally {
      if (!silent) setChatLoading(false);
    }
  };

  const handleRetryEvaluation = async (pointId) => {
    if (!currentChat?.id || !pointId || retryingEvaluationId) return;
    setRetryingEvaluationId(pointId);
    try {
      await chatService.retryEvaluation(currentChat.id, pointId);
      await fetchMessages(currentChat.id, { silent: true, loadReport: true });
    } catch (err) {
      console.error('Retry interview evaluation failed:', err);
      setError(err.response?.data?.detail || '重新评估失败，请稍后重试。');
    } finally {
      setRetryingEvaluationId(null);
    }
  };

  const handleSelectChat = (chatId, sourceChats = chats) => {
    const selected = sourceChats.find((chat) => chat.id === chatId);

    if (selected) {
      currentChatIdRef.current = chatId;
      messageRequestIdRef.current += 1;
      setFinishRequestedAt(null);
      setChatLoading(false);
      setError(null);
      clearReportState();
      setCurrentChat(selected);
      setMessages(formatChatMessages(selected.messages));
      fetchMessages(chatId, { silent: true, loadReport: true });

      if (isMobile) {
        setDrawerOpen(false);
      }
    }
  };

  const createInterviewSession = (setup) => {
    const newChatId = `interview_${Date.now()}`;
    const baseChat = {
      id: newChatId,
      timestamp: new Date().toISOString(),
      messages: [],
      preview: '开始一场新的模拟面试',
      interviewRole: setup.interviewRole,
      interviewLevel: setup.interviewLevel,
      interviewType: setup.interviewType,
      targetCompany: setup.targetCompany,
      jdContent: setup.jdContent,
      jobPostingId: setup.jobPostingId,
    };
    const meta = deriveInterviewMeta(baseChat);
    const newChat = { ...baseChat, ...meta, status: '新会话' };

    setChats((prev) => [newChat, ...prev]);
    setCurrentChat(newChat);
    setMessages([]);
    clearReportState();
    setFinishRequestedAt(null);

    if (isMobile) {
      setDrawerOpen(false);
    }

    return newChat;
  };

  const handleNewChat = () => {
    if (!currentUser?.has_resume) {
      setError('开始新面试前，请先前往个人档案上传简历。');
      setResumePromptOpen(true);
      return;
    }
    setSetupDialogOpen(true);
  };

  const handleCreateInterview = () => {
    if (!interviewSetup.jobPostingId && !interviewSetup.jdContent.trim()) {
      setError('请选择职位库中的 JD，或先填写手工 JD 内容。');
      return;
    }
    const createdChat = createInterviewSession(interviewSetup);
    setSetupDialogOpen(false);
    startInterviewOpening(createdChat);
  };

  const handleInterviewJobChange = (event) => {
    const jobPostingId = event.target.value;
    const job = interviewJobs.find((item) => String(item.id) === String(jobPostingId));
    setInterviewSetup((prev) => {
      if (!job) return { ...prev, jobPostingId: '', jdContent: '' };
      return {
        ...prev,
        jobPostingId: String(job.id),
        interviewRole: job.title || prev.interviewRole,
        targetCompany: job.company || prev.targetCompany,
        jdContent: buildInterviewJdContext(job) || prev.jdContent,
      };
    });
  };

  const startInterviewOpening = async (activeChat) => {
    if (!activeChat || isStreaming) return;

    const chatId = activeChat.id;
    setIsStreaming(true);
    setStreamingMessage('');
    setError(null);

    try {
      streamingService.startStream('开始面试', chatId, {
        onChunk: (chunk) => {
          setStreamingMessage((prev) => prev + (chunk || ''));
        },
        onComplete: () => {
          setStreamingMessage((finalContent) => {
            if (finalContent && finalContent.trim()) {
              setMessages((prev) => [
                ...prev,
                {
                  id: `msg_${Date.now()}_opening`,
                  content: finalContent,
                  role: 'assistant',
                  timestamp: new Date().toISOString(),
                },
              ]);
            } else {
              setError('没有收到首道面试题，请重试。');
            }

            return '';
          });

          setIsStreaming(false);
          fetchChats({ silent: true });
        },
        onError: (streamError) => {
          console.error('Opening interview stream error:', streamError);
          setError(streamError.message || '自动发起首题失败，请重试。');
          setIsStreaming(false);
        },
      }, {
        interviewRole: activeChat.role,
        interviewLevel: activeChat.level,
        interviewType: activeChat.interviewType,
        targetCompany: activeChat.targetCompany,
        jdContent: activeChat.jdContent,
        codeExecution: latestCodeExecution,
      });
      setLatestCodeExecution(null);
    } catch (streamError) {
      console.error('Error starting opening interview question:', streamError);
      setError('自动开始面试失败，请重试。');
      setIsStreaming(false);
    }
  };

  const finishInterviewAndPersist = async (activeChat) => new Promise((resolve, reject) => {
    if (!activeChat?.id) {
      reject(new Error('当前没有可结束的面试会话。'));
      return;
    }

    let finalContent = '';

    setIsStreaming(true);
    setStreamingMessage('');
    setError(null);

    try {
      streamingService.startStream(MANUAL_FINISH_COMMAND, activeChat.id, {
        onChunk: (chunk) => {
          finalContent += chunk || '';
          setStreamingMessage((prev) => prev + (chunk || ''));
        },
        onComplete: () => {
          setStreamingMessage('');

          if (!finalContent.trim()) {
            setIsStreaming(false);
            reject(new Error('没有收到结束面试确认，请重试。'));
            return;
          }

          setMessages((prev) => [
            ...prev,
            {
              id: `msg_${Date.now()}_finish`,
              content: finalContent,
              role: 'assistant',
              timestamp: new Date().toISOString(),
            },
          ]);

          setIsStreaming(false);
          fetchChats({ silent: true });
          resolve(finalContent);
        },
        onError: (streamError) => {
          console.error('Interview finish stream error:', streamError);
          setStreamingMessage('');
          setIsStreaming(false);
          reject(streamError);
        },
      }, {
        interviewRole: activeChat.role,
        interviewLevel: activeChat.level,
        interviewType: activeChat.interviewType,
        targetCompany: activeChat.targetCompany,
        jdContent: activeChat.jdContent,
      });
    } catch (streamError) {
      console.error('Error finishing interview:', streamError);
      setStreamingMessage('');
      setIsStreaming(false);
      reject(streamError);
    }
  });

  const handleFinishInterview = async () => {
    if (!currentChat?.id || isStreaming || finishExportLoading) return;
    if (isInterviewFinished()) return;

    const requestedAt = new Date().toISOString();
    setFinishRequestedAt(requestedAt);
    setFinishExportLoading(true);
    setError(null);

    try {
      const finishResponse = await finishInterviewAndPersist(currentChat);
      if (!includesInterviewEndMarker(finishResponse)) {
        throw new Error('结束面试失败，请稍后重试。');
      }

      const latestReport = await fetchInterviewReport(currentChat.id, { rethrow: true });
      if (!latestReport) {
        throw new Error('生成面试报告失败，请稍后重试。');
      }
    } catch (finishError) {
      console.error('Error finishing interview:', finishError);
      setError(finishError.message || '结束面试失败，请稍后重试。');
      if (!isInterviewFinished()) {
        setFinishRequestedAt(null);
      }
    } finally {
      setFinishExportLoading(false);
    }
  };

  const handleReportAction = () => {
    if (isInterviewFinished()) {
      navigate(`/chat/${currentChat.id}/evaluation`);
      return;
    }

    handleFinishInterview();
  };

  const applySessionState = (chatId, session) => {
    const updateChat = (chat) => {
      if (!chat || chat.id !== chatId) return chat;
      return {
        ...chat,
        interviewStatus: session.status,
        interviewPausedAt: session.paused_at || null,
        interviewPausedSeconds: Number(session.paused_seconds) || 0,
      };
    };
    setChats((prev) => prev.map(updateChat));
    setCurrentChat((prev) => updateChat(prev));
    setTimeNow(Date.now());
  };

  const handlePauseToggle = async () => {
    if (!currentChat?.id || isStreaming || finishExportLoading || currentInterviewFinished) return;
    setSessionActionLoading(true);
    setError(null);
    try {
      const session = currentChat.interviewStatus === 'paused'
        ? await chatService.resumeInterview(currentChat.id)
        : await chatService.pauseInterview(currentChat.id);
      applySessionState(currentChat.id, session);
    } catch (sessionError) {
      console.error('Error updating interview session state:', sessionError);
      setError(sessionError.response?.data?.detail || '更新面试状态失败，请稍后重试。');
    } finally {
      setSessionActionLoading(false);
    }
  };

  const handleDeleteInterview = async () => {
    if (!deleteTarget?.id || sessionActionLoading || isStreaming) return;
    setSessionActionLoading(true);
    setError(null);
    try {
      await chatService.deleteInterview(deleteTarget.id);
      const remainingChats = chats.filter((chat) => chat.id !== deleteTarget.id);
      const deletingCurrent = currentChat?.id === deleteTarget.id;
      setChats(remainingChats);
      setDeleteTarget(null);

      if (deletingCurrent) {
        setCurrentChat(null);
        setMessages([]);
        clearReportState();
        setFinishRequestedAt(null);
        if (remainingChats[0]) {
          handleSelectChat(remainingChats[0].id, remainingChats);
        }
      }
    } catch (deleteError) {
      console.error('Error deleting interview:', deleteError);
      setError(deleteError.response?.data?.detail || '删除面试记录失败，请稍后重试。');
    } finally {
      setSessionActionLoading(false);
    }
  };

  const handleSendMessage = async (message) => {
    if (!message.trim() || isStreaming || isInterviewFinished()) return;
    if (currentChat?.interviewStatus === 'paused') {
      setError('该面试已暂停，请先继续面试后再提交回答。');
      return;
    }
    if (!currentChat && !currentUser?.has_resume) {
      setError('开始面试前，请先前往个人档案上传简历。');
      setResumePromptOpen(true);
      return;
    }

    const activeChat = currentChat || (() => {
      return createInterviewSession(interviewSetup);
    })();

    const chatId = activeChat.id;

    const userMessage = {
      id: `msg_${Date.now()}`,
      content: message,
      role: 'user',
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setIsStreaming(true);
    setStreamingMessage('');

    try {
      streamingService.startStream(message, chatId, {
        onChunk: (chunk) => {
          setStreamingMessage((prev) => prev + (chunk || ''));
        },
        onComplete: () => {
          setStreamingMessage((finalContent) => {
            if (finalContent && finalContent.trim()) {
              setMessages((prev) => [
                ...prev,
                {
                  id: `msg_${Date.now()}_response`,
                  content: finalContent,
                  role: 'assistant',
                  timestamp: new Date().toISOString(),
                },
              ]);

              if (includesInterviewEndMarker(finalContent)) {
                fetchInterviewReport(chatId);
              }
            } else {
              setError('没有收到面试官反馈，请重试。');
            }

            return '';
          });

          setIsStreaming(false);
          fetchChats({ silent: true });
        },
        onError: (streamError) => {
          console.error('Streaming error:', streamError);
          setError(streamError.message || '获取下一道面试题失败，请重试。');
          setIsStreaming(false);
        },
      }, {
        interviewRole: activeChat.role,
        interviewLevel: activeChat.level,
        interviewType: activeChat.interviewType,
        targetCompany: activeChat.targetCompany,
        jdContent: activeChat.jdContent,
      });
    } catch (sendError) {
      console.error('Error sending message:', sendError);
      setError('提交回答失败，请重试。');
      setIsStreaming(false);
    }
  };

  const handleRunCode = async ({ language, sourceCode, stdin, expectedOutput, onProgress }) => {
    const response = await chatService.runCode({
      language,
      sourceCode,
      stdin,
      expectedOutput,
      onProgress,
    });
    setLatestCodeExecution({
      language,
      status: response.status,
      passed: response.passed,
      time: response.time,
      memory: response.memory,
      stdout: response.stdout,
      stderr: response.stderr,
      compile_output: response.compile_output,
      message: response.message,
    });
    return response;
  };

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const currentInterviewFinished = isInterviewFinished();
  const completedAnswerCount = getCompletedAnswerCount(currentChat?.messages || []);
  const assistantQuestionCount = Math.max(1, currentInterviewFinished ? completedAnswerCount : completedAnswerCount + 1);
  const currentEndedAt = currentInterviewFinished
    ? messages
      .map(getMessageTimestamp)
      .filter(Boolean)
      .reduce((latest, timestamp) => Math.max(latest, timestamp), 0)
    : null;
  const timingStoppedAt = currentEndedAt ? new Date(currentEndedAt).toISOString() : finishRequestedAt;
  const currentStatus = (() => {
    if (currentInterviewFinished) return '已完成';
    if (finishRequestedAt) return '结束中';
    if (currentChat?.interviewStatus === 'paused') return '已暂停';
    if (messages.length > 0 || isStreaming) return '进行中';
    return currentChat?.status || '待开始';
  })();
  const baseCurrentMeta = currentChat || {
    role: 'Web前端工程师',
    level: '中级',
    interviewType: '一面',
    score: null,
    status: '待开始',
    startedAt: new Date(timeNow).toISOString(),
    endedAt: null,
    isFinished: false,
    estimatedMinutes: getEstimatedInterviewMinutes('一面'),
    duration: `预计 ${getEstimatedInterviewMinutes('一面')} 分钟`,
    questionCount: Math.max(1, assistantQuestionCount || 1),
    targetQuestions: getInterviewQuestionLimit('一面'),
    title: 'AI 面试房间',
  };
  const currentMeta = {
    ...baseCurrentMeta,
    questionCount: Math.max(1, assistantQuestionCount || baseCurrentMeta.questionCount || 1),
    targetQuestions: baseCurrentMeta.targetQuestions || getInterviewQuestionLimit(baseCurrentMeta.interviewType),
    estimatedMinutes: baseCurrentMeta.estimatedMinutes || getEstimatedInterviewMinutes(baseCurrentMeta.interviewType),
    isFinished: currentInterviewFinished || !!finishRequestedAt || baseCurrentMeta.isFinished,
    isPaused: !currentInterviewFinished && currentChat?.interviewStatus === 'paused',
    pausedAt: baseCurrentMeta.pausedAt || null,
    pausedSeconds: baseCurrentMeta.pausedSeconds || 0,
    endedAt: timingStoppedAt || baseCurrentMeta.endedAt,
    status: currentStatus,
  };
  const currentTimeCopy = buildInterviewTimeCopy(currentMeta, timeNow);
  const latestMessageEvaluation = getLatestEvaluation(messages);
  const latestCodingPrompt = [...messages]
    .reverse()
    .find((message) => message.role === 'assistant' && looksLikeCodingQuestion(getMessageContent(message)))
    ?.content || '';
  const displayedScore = report?.overall_score ?? latestMessageEvaluation?.overall_score ?? currentMeta.score;
  const evaluationDisplay = report?.total_answers > 0
    ? report
    : latestMessageEvaluation
      ? {
        ...latestMessageEvaluation,
        content_analysis: latestMessageEvaluation.summary,
      }
      : null;
  const competencyItems = report?.competency_assessments?.length
    ? report.competency_assessments
    : (latestMessageEvaluation?.capability_assessments || []).map((item) => ({
      capability: item.capability,
      score: item.score,
      confidence: latestMessageEvaluation?.confidence_level || '低',
      covered_questions: 1,
      evidence: item.evidence || [],
      missing_points: item.missing_points || [],
    }));
  const jdRequirementItems = report?.jd_requirement_matches || latestMessageEvaluation?.jd_requirement_matches || [];
  const sidebar = (
    <>
      <Toolbar sx={{ alignItems: 'stretch', px: 2.5, py: 1.5, flexShrink: 0 }}>
        <Box sx={{ width: '100%' }}>
          <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={1.2} sx={{ mt: 0.4 }}>
            <Typography variant="h6">
              模拟面试
            </Typography>
            <Button
              variant="contained"
              startIcon={<AddIcon />}
              onClick={handleNewChat}
              sx={{
                borderRadius: 999,
                px: 1.7,
                py: 0.8,
                minWidth: 0,
                minHeight: 0,
                fontSize: '0.92rem',
                whiteSpace: 'nowrap',
                background: 'linear-gradient(90deg, #0ea5e9 0%, #38bdf8 100%)',
                color: '#04101c',
                boxShadow: '0 12px 30px rgba(14,165,233,0.24)',
              }}
            >
              开始新面试
            </Button>
          </Stack>
        </Box>
      </Toolbar>
      <Divider />

      {loading && chats.length === 0 ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', p: 3 }}>
          <CircularProgress />
        </Box>
      ) : (
        <List sx={{ px: 1.5, py: 2, flex: 1, overflowY: 'auto', minHeight: 0 }}>
          {chats.length === 0 ? (
            <Paper
              elevation={0}
              sx={{
                p: 2.5,
                mx: 1,
                borderRadius: 2,
                bgcolor: 'rgba(125,211,252,0.05)',
              }}
            >
              <Typography variant="subtitle2" sx={{ color: '#0f172a' }}>
                还没有面试记录
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                从第一场模拟面试开始，逐步建立你的练习记录。
              </Typography>
            </Paper>

          ) : (
            chats.map((chat) => (
              <ListItem
                key={chat.id}
                disablePadding
                sx={{ mb: 1.2 }}
                secondaryAction={(
                  <Tooltip title="删除面试记录">
                    <span>
                      <IconButton
                        edge="end"
                        aria-label={`删除 ${chat.title}`}
                        onClick={() => setDeleteTarget(chat)}
                        disabled={isStreaming || sessionActionLoading}
                        sx={{ color: 'rgba(248,113,113,0.84)' }}
                      >
                        <DeleteOutlineRoundedIcon fontSize="small" />
                      </IconButton>
                    </span>
                  </Tooltip>
                )}
              >
                <ListItemButton
                  selected={currentChat?.id === chat.id}
                  onClick={() => handleSelectChat(chat.id)}
                  sx={{
                    borderRadius: 2,
                    px: 2,
                    pr: 5.5,
                    py: 1.8,
                    alignItems: 'flex-start',
                    border: currentChat?.id === chat.id
                      ? '1px solid rgba(125,211,252,0.24)'
                      : '1px solid rgba(148,163,184,0.08)',
                    bgcolor: currentChat?.id === chat.id
                      ? 'rgba(125,211,252,0.08)'
                      : '#ffffff',
                  }}
                >
                  <Box sx={{ width: '100%' }}>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 0.5, mb: 0.6 }}>
                      <Typography variant="subtitle2" sx={{ color: '#0f172a' }}>
                        {chat.title}
                      </Typography>
                      <Typography variant="body2" sx={{ color: '#475569' }}>
                      {chat.level}
                      </Typography>
                      <Chip
                        label={chat.score == null ? '待评估' : chat.score}
                        size="small"
                        sx={{
                          height: 24,
                          bgcolor: chat.score == null ? 'rgba(148,163,184,0.12)' : 'rgba(52,211,153,0.12)',
                          color: chat.score == null ? '#cbd5e1' : '#34d399',
                          fontWeight: 700,
                        }}
                      />
                     
                    </Box>
                    
                    <Typography
                      variant="caption"
                      sx={{
                        mt: 0.7,
                        display: 'block',
                        color: '#64748b',
                      }}
                    >
                      {chat.questionCount}/{chat.targetQuestions} 题 · {buildInterviewTimeCopy(chat, timeNow).short}
                    </Typography>
                  </Box>
                </ListItemButton>
              </ListItem>
            ))
          )}
        </List>
      )}
    </>
  );

  return (
    <Box sx={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      <Dialog
        open={!!deleteTarget}
        onClose={() => !sessionActionLoading && setDeleteTarget(null)}
        fullWidth
        maxWidth="xs"
        PaperProps={{
          sx: {
            borderRadius: 2,
            background: '#ffffff',
            border: '1px solid rgba(248,113,113,0.22)',
          },
        }}
      >
        <DialogTitle>删除面试记录？</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.7 }}>
            将永久删除本场面试的全部问答和报告数据，此操作无法撤销。
          </Typography>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2.5 }}>
          <Button onClick={() => setDeleteTarget(null)} disabled={sessionActionLoading} color="inherit">
            取消
          </Button>
          <Button onClick={handleDeleteInterview} disabled={sessionActionLoading} color="error" variant="contained">
            {sessionActionLoading ? '删除中...' : '删除'}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog
        open={resumePromptOpen}
        onClose={() => setResumePromptOpen(false)}
        fullWidth
        maxWidth="xs"
        PaperProps={{
          sx: {
            borderRadius: 2.5,
            background: 'linear-gradient(180deg, #ffffff 0%, #f8fbff 100%)',
            border: '1px solid rgba(251, 191, 36, 0.18)',
          },
        }}
      >
        <DialogTitle sx={{ px: 4, pt: 4, pb: 1.5 }}>
          <Typography variant="h6">请先完善个人简历</Typography>
        </DialogTitle>
        <DialogContent sx={{ px: 4, pt: 1.5, pb: 1 }}>
          <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.8 }}>
            当前还没有检测到可用于面试的简历信息。完善个人档案并上传简历后，系统才能结合你的经历生成更贴合的面试问题。
          </Typography>
        </DialogContent>
        <DialogActions sx={{ px: 4, pb: 4, pt: 2 }}>
          <Button onClick={() => setResumePromptOpen(false)} sx={{ color: '#475569' }}>
            取消
          </Button>
          <Button
            variant="contained"
            onClick={() => {
              setResumePromptOpen(false);
              navigate('/profile');
            }}
            sx={{
              borderRadius: 2,
              background: 'linear-gradient(90deg, #f59e0b 0%, #fbbf24 100%)',
              color: '#1f1300',
            }}
          >
            去完善简历
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog
        open={setupDialogOpen}
        onClose={() => setSetupDialogOpen(false)}
        fullWidth
        maxWidth="md"
        PaperProps={{
          sx: {
            width: 'min(720px, calc(100% - 32px))',
            minHeight: 470,
            borderRadius: 2.5,
            background: 'linear-gradient(180deg, #ffffff 0%, #f8fbff 100%)',
            border: '1px solid rgba(125, 211, 252, 0.12)',
          },
        }}
      >
        <DialogTitle sx={{ px: 4, pt: 4, pb: 1.5 }}>
          <Typography variant="h6">创建新的模拟面试</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.8 }}>
            先选择岗位、级别和面试类型，再进入对应的面试会话。面试会自动结合个人档案中的简历内容发问。
          </Typography>
        </DialogTitle>
        <DialogContent sx={{ px: 4, pt: 3, pb: 1.5, overflowY: 'visible' }}>
          <Stack spacing={2.5} sx={{ mt: 1.5 }}>
            <Paper
              elevation={0}
              sx={{
                p: 1.8,
                borderRadius: 2,
                bgcolor: 'rgba(125,211,252,0.06)',
                border: '1px solid rgba(125, 211, 252, 0.24)',
              }}
            >
              <Typography variant="subtitle2" sx={{ color: '#0f172a' }}>
                当前档案简历
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75, lineHeight: 1.7 }}>
                {currentUser?.has_resume
                  ? `${currentUser.resume_file_name || '已上传简历'} 已关联到本次面试，会根据你的简历经历、技能和目标岗位展开提问。`
                  : '未检测到简历，请先到个人档案上传。'}
              </Typography>
            </Paper>

            <TextField
              select
              fullWidth
              label="目标 JD"
              value={interviewSetup.jobPostingId}
              onChange={handleInterviewJobChange}
              disabled={interviewJobsLoading}
              helperText={interviewJobsError || (interviewSetup.jobPostingId ? '已带入职位库中的岗位、公司和 JD；仍可在下方微调。' : '选择已导入的职位后，将自动带入岗位、公司和 JD。')}
            >
              <MenuItem value="">不使用职位库 JD（手工填写）</MenuItem>
              {interviewJobs.map((job) => (
                <MenuItem key={job.id} value={String(job.id)}>
                  {job.title || '未命名职位'}{job.company ? ` - ${job.company}` : ''}
                </MenuItem>
              ))}
            </TextField>

            <TextField
              key={interviewSetup.jobPostingId ? 'job-jd-editor' : 'manual-jd-editor'}
              fullWidth
              multiline
              minRows={5}
              maxRows={10}
              autoFocus={!interviewSetup.jobPostingId}
              label={interviewSetup.jobPostingId ? 'JD 内容（可编辑）' : '手工填写 JD'}
              placeholder="请输入岗位职责、任职要求、技术栈和加分项。"
              value={interviewSetup.jdContent}
              onChange={(e) => setInterviewSetup((prev) => ({ ...prev, jdContent: e.target.value }))}
              helperText={interviewSetup.jobPostingId
                ? '职位库 JD 已自动带入，你可以继续修改。'
                : '当前为手工模式，填写后会直接用于本场面试。'}
            />

            <TextField
              select
              fullWidth
              label="目标岗位"
              value={interviewSetup.interviewRole}
              onChange={(e) => setInterviewSetup((prev) => ({ ...prev, interviewRole: e.target.value }))}
            >
              {!roleOptions.includes(interviewSetup.interviewRole) && (
                <MenuItem value={interviewSetup.interviewRole}>{interviewSetup.interviewRole}</MenuItem>
              )}
              {roleOptions.map((option) => (
                <MenuItem key={option} value={option}>
                  {option}
                </MenuItem>
              ))}
            </TextField>

            <TextField
              select
              fullWidth
              label="面试级别"
              value={interviewSetup.interviewLevel}
              onChange={(e) => setInterviewSetup((prev) => ({ ...prev, interviewLevel: e.target.value }))}
            >
              {levelOptions.map((option) => (
                <MenuItem key={option} value={option}>
                  {option}
                </MenuItem>
              ))}
            </TextField>

              <TextField
              fullWidth
              label="目标公司"
              placeholder="例如：字节跳动 / 阿里巴巴 / 腾讯"
              value={interviewSetup.targetCompany}
              onChange={(e) => setInterviewSetup((prev) => ({ ...prev, targetCompany: e.target.value }))}
            />

            <TextField
              select
              fullWidth
              label="面试类型"
              value={interviewSetup.interviewType}
              onChange={(e) => setInterviewSetup((prev) => ({ ...prev, interviewType: e.target.value }))}
            >
              {interviewTypeOptions.map((option) => (
                <MenuItem key={option} value={option}>
                  {option}
                </MenuItem>
              ))}
            </TextField>

            <Paper
              elevation={0}
              sx={{
                p: 1.8,
                borderRadius: 2,
                bgcolor: 'rgba(52,211,153,0.06)',
                border: '1px solid rgba(52,211,153,0.12)',
              }}
            >
              <Typography variant="subtitle2" sx={{ color: '#0f172a' }}>
                本场节奏
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75, lineHeight: 1.7 }}>
                {interviewSetup.interviewType}预计 {getEstimatedInterviewMinutes(interviewSetup.interviewType)} 分钟，约 {getInterviewQuestionLimit(interviewSetup.interviewType)} 道题。系统会根据你的回答继续追问，实际用时会随作答深度浮动。
              </Typography>
            </Paper>

          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 4, pb: 4, pt: 2 }}>
          <Button onClick={() => setSetupDialogOpen(false)} sx={{ color: '#475569' }}>
            取消
          </Button>
          <Button
            variant="contained"
            onClick={handleCreateInterview}
            sx={{
              borderRadius: 2,
              background: 'linear-gradient(90deg, #0ea5e9 0%, #38bdf8 100%)',
              color: '#04101c',
            }}
          >
            开始面试
          </Button>
        </DialogActions>
      </Dialog>

      <AppBar
        position="fixed"
        sx={{
          width: { lg: sidebarCollapsed ? '100%' : `calc(100% - ${drawerWidth}px)` },
          ml: { lg: sidebarCollapsed ? 0 : `${drawerWidth}px` },
          transition: theme.transitions.create(['width', 'margin'], {
            easing: theme.transitions.easing.sharp,
            duration: theme.transitions.duration.standard,
          }),
        }}
      >
        <Toolbar sx={{ gap: 2 }}>
          <IconButton
            color="inherit"
            edge="start"
            onClick={() => {
              if (isMobile) {
                setDrawerOpen(!drawerOpen);
              } else {
                setSidebarCollapsed((prev) => !prev);
              }
            }}
          >
            <MenuIcon />
          </IconButton>

          <Box sx={{ flexGrow: 1 }}>
            
            <Typography variant="h6" noWrap>
              {currentMeta.title || 'AI 面试房间'}
            </Typography>
          </Box>

          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ display: { xs: 'none', md: 'flex' } }}>
            <Chip icon={<WorkOutlineRoundedIcon />} label={currentMeta.role} sx={{ bgcolor: 'rgba(125,211,252,0.10)', color: '#0284c7' }} />
            <Chip icon={<TrackChangesRoundedIcon />} label={`第 ${Math.max(1, assistantQuestionCount)} / ${currentMeta.targetQuestions} 题`} sx={{ bgcolor: 'rgba(245,158,11,0.10)', color: '#b45309' }} />
            <Chip icon={<ScheduleRoundedIcon />} label={currentTimeCopy.short} sx={{ bgcolor: 'rgba(148,163,184,0.12)', color: '#475569' }} />
          </Stack>

          <Tooltip title={currentMeta.isPaused ? '继续面试并恢复计时' : '暂停面试并冻结计时'}>
            <span>
              <IconButton
                color="inherit"
                aria-label={currentMeta.isPaused ? '继续面试' : '暂停面试'}
                onClick={handlePauseToggle}
                disabled={!currentChat?.id || isStreaming || finishExportLoading || currentInterviewFinished || sessionActionLoading}
                sx={{ color: currentMeta.isPaused ? '#34d399' : '#cbd5e1' }}
              >
                {currentMeta.isPaused ? <PlayCircleOutlineRoundedIcon /> : <PauseCircleOutlineRoundedIcon />}
              </IconButton>
            </span>
          </Tooltip>

          <Button color="inherit" onClick={() => navigate('/profile')} startIcon={<AccountCircleRoundedIcon />}>
            个人档案
          </Button>
          <Button color="inherit" onClick={() => navigate('/training')} startIcon={<AutoGraphRoundedIcon />}>
            训练营
          </Button>
          <Button
            color="inherit"
            onClick={() => navigate('/voice', {
              state: {
                interviewContext: {
                  chatId: currentChat?.id || null,
                  interviewRole: currentMeta.role,
                  interviewLevel: currentMeta.level,
                  interviewType: currentMeta.interviewType,
                  targetCompany: currentMeta.targetCompany || '',
                  jdContent: currentChat?.jdContent || '',
                },
              },
            })}
            startIcon={<MicIcon />}
            sx={{ mr: 1 }}
          >
            语音面试房间
          </Button>
          <Button color="inherit" onClick={handleLogout} startIcon={<LogoutIcon />}>
            退出登录
          </Button>
        </Toolbar>
      </AppBar>

      <Drawer
        variant={isMobile ? 'temporary' : 'permanent'}
        open={isMobile ? drawerOpen : !sidebarCollapsed}
        onClose={() => setDrawerOpen(false)}
        sx={{
          width: { xs: drawerWidth, lg: sidebarCollapsed ? 0 : drawerWidth },
          flexShrink: 0,
          transition: theme.transitions.create('width', {
            easing: theme.transitions.easing.sharp,
            duration: theme.transitions.duration.standard,
          }),
          '& .MuiDrawer-paper': {
            width: drawerWidth,
            boxSizing: 'border-box',
            bgcolor: '#ffffff',
            borderRight: '1px solid rgba(148, 163, 184, 0.18)',
            backgroundImage: 'linear-gradient(180deg, #ffffff 0%, #f8fbff 100%)',
            display: 'flex',
            flexDirection: 'column',
            overflowX: 'hidden',
            transform: {
              lg: sidebarCollapsed ? `translateX(-${drawerWidth}px)` : 'translateX(0)',
            },
            transition: theme.transitions.create('transform', {
              easing: theme.transitions.easing.sharp,
              duration: theme.transitions.duration.standard,
            }),
          },
        }}
      >
        {sidebar}
      </Drawer>

      <Box
        component="main"
        sx={{
          flexGrow: 1,
          width: { lg: sidebarCollapsed ? '100%' : `calc(100% - ${drawerWidth}px)` },
          height: '100vh',
          display: 'grid',
          gridTemplateColumns: { xs: '1fr', lg: 'minmax(0, 1fr) 340px' },
          overflow: 'hidden',
          minHeight: 0,
          transition: theme.transitions.create('width', {
            easing: theme.transitions.easing.sharp,
            duration: theme.transitions.duration.standard,
          }),
        }}
      >
        <Box
          sx={{
            display: 'flex',
            flexDirection: 'column',
            minWidth: 0,
            minHeight: 0,
            height: '100vh',
            overflow: 'hidden',
          }}
        >
          <Toolbar />

          <Box
            sx={{
              flexGrow: 1,
              px: { xs: 2, md: 3 },
              pt: { xs: 2, md: 3 },
              pb: 2,
              overflowY: 'auto',
              display: 'flex',
              flexDirection: 'column',
              minHeight: 0,
              WebkitOverflowScrolling: 'touch',
            }}
          >
            {chatLoading ? (
              <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
                <CircularProgress />
              </Box>
            ) : error ? (
              <Paper elevation={0} sx={{ p: 3, borderRadius: 2, bgcolor: 'rgba(239,68,68,0.08)' }}>
                <Typography color="error">{error}</Typography>
              </Paper>
            ) : messages.length === 0 && !currentChat ? (
              <Paper
                elevation={0}
                sx={{
                  p: 4,
                  borderRadius: 2.5,
                  mt: 2,
                  textAlign: 'center',
                  bgcolor: '#ffffff',
                }}
              >
                <Typography variant="h5" gutterBottom>
                  开始一场模拟面试
                </Typography>
                <Typography variant="body1" color="text.secondary" sx={{ maxWidth: 560, mx: 'auto' }}>
                  你可以从左侧选择已有会话，或者新建一场面试，体验带追问的结构化 AI 面试流程。
                </Typography>
                <Button
                  variant="contained"
                  startIcon={<AddIcon />}
                  onClick={handleNewChat}
                  sx={{
                    mt: 3,
                    borderRadius: 2.5,
                    background: 'linear-gradient(90deg, #0ea5e9 0%, #38bdf8 100%)',
                    color: '#04101c',
                  }}
                >
                  开始面试
                </Button>
              </Paper>
            ) : (
              <>
                {messages.map((message) => (
                  <MessageBubble
                    key={message.id}
                    content={message.content}
                    role={message.role}
                  />
                ))}

                {isStreaming && (
                  <MessageBubble content={streamingMessage} role="assistant" isStreaming />
                )}

                <div ref={messagesEndRef} />
              </>
            )}
          </Box>

          {(currentChat || messages.length > 0) && (
            currentInterviewFinished && !isStreaming ? (
              <Alert severity="success" sx={{ mt: 1.5, mb: 1.5 }}>
                本场面试已结束。问答记录已保留，请点击右侧“进行评估”查看评估结果。
              </Alert>
            ) : null
          )}

          {(currentChat || messages.length > 0) && !currentInterviewFinished && (
            <ChatInput
              onSendMessage={handleSendMessage}
              onRunCode={handleRunCode}
              latestCodingPrompt={latestCodingPrompt}
              disabled={isStreaming || isInterviewFinished() || currentMeta.isPaused}
            />
          )}
        </Box>

        <Box
          sx={{
            display: { xs: 'none', lg: 'block' },
            p: 3,
            pt: 11,
            borderLeft: '1px solid rgba(148, 163, 184, 0.18)',
            background: '#f8fbff',
            height: '100vh',
            overflowY: 'auto',
            minHeight: 0,
            WebkitOverflowScrolling: 'touch',
          }}
        >
          <Stack spacing={2.2}>
            <Paper
              elevation={0}
              sx={{
                p: 2.5,
                borderRadius: 2.5,
                bgcolor: '#ffffff',
                backgroundImage: 'linear-gradient(135deg, rgba(14,165,233,0.08) 0%, #ffffff 68%)',
              }}
            >
              <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1.5}>
                <Box sx={{ minWidth: 0, flex: 1 }}>
                  
                  <Typography
                    sx={{
                      mt: 0.35,
                      mb: 1,
                      fontSize: { xs: '1.25rem', md: '1.45rem' },
                      fontWeight: 700,
                      lineHeight: 1.2,
                      color: '#0f172a',
                    }}
                  >
                    {currentMeta.role}
                  </Typography>
                </Box>
                
              </Stack>
              
                <Button
                  size="small"
                  variant="outlined"
                  onClick={handleReportAction}
                  disabled={!currentChat?.id || reportLoading || isStreaming || finishExportLoading}
                  sx={{
                    borderColor: 'rgba(125,211,252,0.24)',
                    color: '#0284c7',
                    borderRadius: 2,
                    whiteSpace: 'nowrap',
                    flexShrink: 0,
                    
                  }}
                >
                  {finishExportLoading || reportLoading
                    ? '处理中...'
                    : isInterviewFinished()
                      ? '进行评估'
                      : '结束面试'}
                </Button>
               
              

                <Stack direction="row" spacing={0.8} useFlexGap flexWrap="wrap" alignItems="flex-start">
                  <Chip
                    size="small"
                    label={currentMeta.level}
                    sx={{
                      bgcolor: 'rgba(125,211,252,0.10)',
                      color: '#0284c7',
                      mt: 1,
                      pt: 0.4,
                      borderRadius: '16px',
                      fontSize: '0.8rem',
                      px: 1,
                      minWidth: 'fit-content',
                      fontWeight: 'bold',  // 加粗字体
                      
                    }}
                  />

                  <Chip
                    size="small"
                    label={currentMeta.interviewType}
                    sx={{
                      bgcolor: 'rgba(148,163,184,0.12)',
                      color: '#475569',
                      mt: 1,
                      pt: 0.4,
                      borderRadius: '16px',
                      fontSize: '0.75rem',
                      px: 1,
                      fontWeight: 'bold',  // 加粗字体
                    }}
                  />

                  <Chip
                    size="small"
                    label={currentInterviewFinished ? '已结束' : currentMeta.status}
                    sx={{
                      bgcolor: 'rgba(52,211,153,0.10)',
                      color: '#059669',
                      mt: 1,
                      pt: 0.4,
                      borderRadius: '16px',
                      fontSize: '0.75rem',
                      px: 1,
                      fontWeight: 'bold',  // 加粗字体
                    }}
                  />

                  <Chip
                    size="small"
                    icon={<ScheduleRoundedIcon />}
                    label={currentTimeCopy.detail}
                    sx={{
                      bgcolor: 'rgba(148,163,184,0.12)',
                      color: '#475569',
                      mt: 1,
                      pt: 0.4,
                      borderRadius: '16px',
                      fontSize: '0.75rem',
                      px: 1,
                      fontWeight: 'bold',
                    }}
                  />

                  <Chip
                    size="small"
                    label={displayedScore == null ? 'ai评分待生成' : `ai评分 ${displayedScore}`}
                    sx={{
                      bgcolor: 'rgba(245,158,11,0.10)',
                      color: '#b45309',
                      mt: 1,
                      pt: 0.4,
                      borderRadius: '16px',
                      fontSize: '0.75rem',
                      px: 1,
                      fontWeight: 'bold',  // 加粗字体
                    }}
                  />
                </Stack>

              <Box
                sx={{
                  mt: 2,
                  pt: 2,
                  borderTop: '1px solid rgba(148, 163, 184, 0.18)',
                }}
              >
                <Typography variant="subtitle2" sx={{ color: '#0f172a', fontWeight: 700 }}>
                  报告摘要
                </Typography>
                {reportLoading ? (
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                    正在生成本场面试报告...
                  </Typography>
                ) : report ? (
                  <>
                    {evaluationExportNotice && (
                      <Alert severity="info" sx={{ mt: 1, mb: 1, py: 0.25 }}>
                        {evaluationExportNotice}
                      </Alert>
                    )}
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                      {report.summary}
                    </Typography>
                    <Typography variant="caption" sx={{ mt: 0.6, display: 'block', color: '#2563eb' }}>
                      有效作答轮次：{getEffectiveAnswerCount(report)}
                    </Typography>
                  </>
                ) : (
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                    面试过程中不再逐轮展示评分。完成作答后，可在这里统一查看本场面试报告。
                  </Typography>
                )}
                {!report && evaluationExportNotice && (
                  <Alert severity="info" sx={{ mt: 1, py: 0.25 }}>
                    {evaluationExportNotice}
                  </Alert>
                )}
              </Box>
            </Paper>

            <Paper
              elevation={0}
              sx={{
                p: 2.5,
                borderRadius: 2.5,
                bgcolor: '#ffffff',
                backgroundImage: 'linear-gradient(180deg, rgba(,0.08) 0%, #ffffff 100%)',
              }}
            >
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.35 }}>
                <WorkOutlineRoundedIcon sx={{ color: '#2563eb', fontSize: 20 }} />
                <Typography variant="subtitle1" sx={{ color: '#0f172a', fontWeight: 700 }}>
                  问答记录与参考答案
                </Typography>
              </Stack>

              {report && report.interview_questions?.length > 0 ? (
                <Stack spacing={1.2} sx={{ maxHeight: 420, overflowY: 'auto', pr: 0.2 }}>
                  {report.interview_questions.map((item, index) => (
                    <Box
                      key={index}
                      sx={{
                        p: 1.35,
                        borderRadius: 2,
                        bgcolor: '#f8fafc',
                        border: '1px solid rgba(147, 197, 253, 0.32)',
                      }}
                    >
                      <Typography variant="caption" sx={{ color: '#2563eb', display: 'block', mb: 0.55 }}>
                        第 {index + 1} 题 · 面试官问题
                      </Typography>
                      <Typography variant="body2" sx={{ color: '#1e293b', lineHeight: 1.7, mb: 1.1, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                        {item.question || '未记录问题'}
                      </Typography>

                      <Typography variant="caption" sx={{ color: '#2563eb', display: 'block', mb: 0.55 }}>
                        候选人回答
                      </Typography>
                      <Typography variant="body2" sx={{ color: '#475569', lineHeight: 1.7, mb: 1.1, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                        {item.candidate_answer || '未记录回答'}
                      </Typography>

                      <Box
                        sx={{
                          mb: 1.1,
                          p: 1,
                          borderRadius: 1.5,
                          bgcolor: item.evaluation_status === 'failed' ? '#fef2f2' : '#eff6ff',
                          border: item.evaluation_status === 'failed'
                            ? '1px solid rgba(239,68,68,0.24)'
                            : '1px solid rgba(147,197,253,0.32)',
                        }}
                      >
                        <Typography variant="caption" sx={{ color: '#2563eb', display: 'block', mb: 0.55 }}>
                          本题评估
                        </Typography>
                        {item.evaluation_status === 'queued' || item.evaluation_status === 'processing' ? (
                          <Stack direction="row" spacing={0.8} alignItems="center">
                            <CircularProgress size={14} />
                            <Typography variant="body2" sx={{ color: '#475569' }}>
                              {item.evaluation_status === 'queued' ? '已进入评估队列，等待处理…' : '正在评估本题…'}
                            </Typography>
                          </Stack>
                        ) : item.evaluation_status === 'failed' ? (
                          <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between">
                            <Typography variant="body2" sx={{ color: '#b91c1c', lineHeight: 1.55 }}>
                              评估失败：{item.evaluation_error || '评估服务暂时不可用，请稍后重试。'}
                            </Typography>
                            {item.point_id && (
                              <Button
                                size="small"
                                variant="outlined"
                                onClick={() => handleRetryEvaluation(item.point_id)}
                                disabled={retryingEvaluationId === item.point_id}
                              >
                                {retryingEvaluationId === item.point_id ? '重试中…' : '重新评估'}
                              </Button>
                            )}
                          </Stack>
                          ) : item.evaluation ? (
                            <Stack direction="row" spacing={0.7} useFlexGap flexWrap="wrap" alignItems="center">
                              <Chip size="small" label={`综合 ${item.evaluation.overall_score ?? 0} 分`} color="primary" />
                              <Chip size="small" label={item.evaluation.verdict || '已完成'} variant="outlined" />
                            {item.evaluation.evaluation_mode === 'fallback' && (
                              <Chip size="small" label="规则降级" color="warning" variant="outlined" />
                            )}
                              {item.evaluation.confidence_level && (
                                <Chip size="small" label={`${item.evaluation.confidence_level}置信度`} variant="outlined" />
                              )}
                              {item.evaluation.evaluation_mode === 'fallback' && item.point_id && (
                                <Button
                                  size="small"
                                  variant="outlined"
                                  onClick={() => handleRetryEvaluation(item.point_id)}
                                  disabled={retryingEvaluationId === item.point_id}
                                >
                                  {retryingEvaluationId === item.point_id ? '重新评估中…' : '重新评估'}
                                </Button>
                              )}
                            {item.evaluation.summary && (
                              <Typography variant="body2" sx={{ width: '100%', color: '#475569', lineHeight: 1.55 }}>
                                {item.evaluation.summary}
                              </Typography>
                            )}
                            {item.evaluation.evaluation_mode === 'fallback' && item.evaluation.evaluation_basis?.length > 0 && (
                              <Box
                                sx={{
                                  width: '100%',
                                  mt: 0.8,
                                  px: 1,
                                  py: 0.8,
                                  bgcolor: 'rgba(245,158,11,0.08)',
                                  border: '1px solid rgba(245,158,11,0.22)',
                                  borderRadius: 1,
                                }}
                              >
                                <Typography variant="caption" sx={{ display: 'block', color: '#92400e', fontWeight: 700, mb: 0.35 }}>
                                  降级评分依据
                                </Typography>
                                {item.evaluation.evaluation_basis.map((basis, basisIndex) => (
                                  <Typography key={`${item.point_id || item.question}-basis-${basisIndex}`} variant="caption" sx={{ display: 'block', color: '#78350f', lineHeight: 1.55 }}>
                                    {basisIndex + 1}. {basis}
                                  </Typography>
                                ))}
                              </Box>
                            )}
                          </Stack>
                        ) : (
                          <Typography variant="body2" sx={{ color: '#64748b' }}>
                            当前暂无评估结果。
                          </Typography>
                        )}
                      </Box>

                      <Typography variant="caption" sx={{ color: '#2563eb', display: 'block', mb: 0.55 }}>
                        参考答案
                      </Typography>
                      <Typography variant="body2" sx={{ color: '#475569', lineHeight: 1.7, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                        {item.reference_answer || '暂无参考答案'}
                      </Typography>
                    </Box>
                  ))}
                </Stack>
              ) : (
                <Box
                  sx={{
                    p: 1.35,
                    borderRadius: 2,
                    bgcolor: '#f8fafc',
                    border: '1px solid rgba(147, 197, 253, 0.32)',
                  }}
                >
                  <Typography variant="body2" sx={{ color: '#1e293b', fontSize: '0.96rem', lineHeight: 1.75 }}>
                    暂无可展示的问答记录。继续完成面试问答后会自动补充这一部分。
                  </Typography>
                </Box>
              )}
            </Paper>

            <Paper
              elevation={0}
              sx={{
                p: 2.5,
                borderRadius: 2.5,
                bgcolor: '#ffffff',
                backgroundImage: 'linear-gradient(180deg, rgba(,0.08) 0%, #ffffff 100%)',
              }}
            >
              <Typography variant="subtitle1" sx={{ color: '#0f172a', mb: 1.5, fontWeight: 700 }}>
                能力评估
              </Typography>
              {evaluationDisplay ? (
                <Stack spacing={1}>
                  {getAvailableReportScores(evaluationDisplay).map((item) => {
                    const ScoreIcon = item.icon;
                    return (
                      <Chip
                        key={item.key}
                        icon={<ScoreIcon />}
                        label={`${item.label}：${evaluationDisplay[item.key]}`}
                        sx={{ justifyContent: 'flex-start', bgcolor: 'rgba(148,163,184,0.08)', color: '#475569' }}
                      />
                    );
                  })}
                  {evaluationDisplay.overall_score !== null && evaluationDisplay.overall_score !== undefined && (
                    <Chip icon={<TipsAndUpdatesRoundedIcon />} label={`综合得分：${evaluationDisplay.overall_score}`} sx={{ justifyContent: 'flex-start', bgcolor: 'rgba(125,211,252,0.12)', color: '#0284c7' }} />
                  )}
                  {getAvailableReportScores(evaluationDisplay).length === 0 && (
                    <Typography variant="body2" sx={{ color: '#64748b' }}>
                      当前暂无有效能力维度数据，已隐藏缺失字段。
                    </Typography>
                  )}
                  {evaluationDisplay.assessment_version === 'rubric-v2' && (
                    <Typography variant="caption" sx={{ color: '#475569', mt: 0.3 }}>
                      本场综合分按题型 Rubric 加权；能力结论会随覆盖题数更新。
                    </Typography>
                  )}
                  {competencyItems.length > 0 && (
                    <Box sx={{ pt: 1.2, mt: 0.2, borderTop: '1px solid rgba(148, 163, 184, 0.18)' }}>
                      <Typography variant="subtitle2" sx={{ color: '#0f172a', fontWeight: 700, mb: 0.8 }}>
                        能力覆盖与置信度
                      </Typography>
                      <Stack spacing={0.85}>
                        {competencyItems.slice(0, 6).map((item) => (
                          <Box key={item.capability}>
                            <Stack direction="row" spacing={0.8} alignItems="center" justifyContent="space-between">
                              <Typography variant="body2" sx={{ color: '#1e293b' }}>
                                {item.capability} · {item.score} 分
                              </Typography>
                              <Chip
                                size="small"
                                label={`${item.covered_questions || 1} 题覆盖 · ${item.confidence || '低'}置信度`}
                                sx={{ height: 22, color: item.confidence === '高' ? '#86efac' : item.confidence === '中' ? '#fde68a' : '#cbd5e1', bgcolor: 'rgba(148,163,184,0.10)' }}
                              />
                            </Stack>
                            {item.missing_points?.[0] && (
                              <Typography variant="caption" sx={{ display: 'block', color: '#64748b', mt: 0.2, lineHeight: 1.55 }}>
                                待补：{item.missing_points[0]}
                              </Typography>
                            )}
                          </Box>
                        ))}
                      </Stack>
                    </Box>
                  )}
                  {jdRequirementItems.length > 0 && (
                    <Box sx={{ pt: 1.2, mt: 0.2, borderTop: '1px solid rgba(148, 163, 184, 0.18)' }}>
                      <Typography variant="subtitle2" sx={{ color: '#0f172a', fontWeight: 700, mb: 0.8 }}>
                        JD 要求核对
                      </Typography>
                      <Stack spacing={0.65}>
                        {jdRequirementItems.slice(0, 5).map((item, index) => (
                          <Stack key={`${item.requirement}-${index}`} direction="row" spacing={0.8} alignItems="flex-start">
                            <Chip
                              size="small"
                              label={item.status || '不适用'}
                              sx={{ height: 21, flexShrink: 0, color: item.status === '已体现' ? '#86efac' : item.status === '部分体现' ? '#fde68a' : '#fda4af', bgcolor: 'rgba(148,163,184,0.10)' }}
                            />
                            <Typography variant="caption" sx={{ color: '#475569', lineHeight: 1.55 }}>
                              {item.requirement}
                            </Typography>
                          </Stack>
                        ))}
                      </Stack>
                    </Box>
                  )}
                  {evaluationDisplay.content_analysis && (
                    <Box
                      sx={{
                        p: 1.4,
                        borderRadius: 2,
                        bgcolor: '#f8fafc',
                        border: '1px solid rgba(125, 211, 252, 0.24)',
                      }}
                    >
                      <Typography variant="subtitle2" sx={{ color: '#0f172a', fontWeight: 700, mb: 0.8 }}>
                        内容分析
                      </Typography>
                      <Typography variant="body2" sx={{ color: '#475569', lineHeight: 1.75 }}>
                        {evaluationDisplay.content_analysis}
                      </Typography>
                    </Box>
                  )}
                </Stack>
              ) : (
                <Stack spacing={1.5}>
                  <Box
                    sx={{
                      p: 1.4,
                      borderRadius: 2,
                      bgcolor: '#f8fafc',
                      border: '1px solid rgba(148,163,184,0.12)',
                    }}
                  >
                    
                    <Typography
                      variant="body2"
                      sx={{
                        mt: 0.9,
                        color: '#475569',
                        fontSize: '0.93rem',
                        lineHeight: 1.65,
                      }}
                    >
                      
                    </Typography>
                  </Box>
                </Stack>
              )}
            </Paper>

            <Paper
              elevation={0}
              sx={{
                p: 2.5,
                borderRadius: 2.5,
                bgcolor: '#ffffff',
                backgroundImage: 'linear-gradient(180deg, rgba(,0.08) 0%, #ffffff 100%)',
              }}
            >
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.35 }}>
                <LightbulbRoundedIcon sx={{ color: '#b45309', fontSize: 20 }} />
                <Typography variant="subtitle1" sx={{ color: '#0f172a', fontWeight: 700 }}>
                作答提示
                </Typography>
              </Stack>
              <Typography variant="body2" sx={{ color: '#64748b', mb: 1.45, lineHeight: 1.7 }}>
                用更短的段落拆开信息，阅读起来会轻很多，也更方便你在作答前快速抓重点。
              </Typography>
              <Stack spacing={1.15}>
                {report && report.recommendations?.length > 0 ? (
                  report.recommendations.map((item, index) => (
                    <Box
                      key={index}
                      sx={{
                        p: 1.35,
                        borderRadius: 2,
                        bgcolor: '#f8fafc',
                        border: '1px solid rgba(245, 158, 11, 0.24)',
                      }}
                    >
                      <Typography
                        variant="body2"
                        sx={{
                          color: '#1e293b',
                          fontSize: '0.96rem',
                          lineHeight: 1.75,
                        }}
                      >
                        {item}
                      </Typography>
                    </Box>
                  ))
                ) : (
                  <>
                    <Box
                      sx={{
                        p: 1.35,
                        borderRadius: 2,
                        bgcolor: '#f8fafc',
                        border: '1px solid rgba(245, 158, 11, 0.24)',
                      }}
                    >
                      <Typography variant="body2" sx={{ color: '#1e293b', fontSize: '0.96rem', lineHeight: 1.75 }}>
                        先给出你的判断，再解释原因，最后补充影响或复盘结论。
                      </Typography>
                    </Box>
                    <Box
                      sx={{
                        p: 1.35,
                        borderRadius: 2,
                        bgcolor: '#f8fafc',
                        border: '1px solid rgba(245, 158, 11, 0.24)',
                      }}
                    >
                      <Typography variant="body2" sx={{ color: '#1e293b', fontSize: '0.96rem', lineHeight: 1.75 }}>
                        如果被问到复杂方案题，先讲假设条件和取舍，再落到具体方案与技术选择。
                      </Typography>
                    </Box>
                  </>
                )}
              </Stack>
            </Paper>

            <Paper
              elevation={0}
              sx={{
                p: 2.5,
                borderRadius: 2.5,
                bgcolor: '#ffffff',
                backgroundImage: 'linear-gradient(180deg, rgba(,0.08) 0%, #ffffff 100%)',
              }}
            >
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.35 }}>
                <MenuBookRoundedIcon sx={{ color: '#059669', fontSize: 20 }} />
                <Typography variant="subtitle1" sx={{ color: '#0f172a', fontWeight: 700 }}>
                推荐资源
                </Typography>
              </Stack>
              {report && report.recommended_resources?.length > 0 ? (
                <Stack spacing={1.2}>
                  {report.recommended_resources.map((resource, index) => (
                    <Box
                      key={index}
                      sx={{
                        p: 1.35,
                        borderRadius: 2,
                        bgcolor: '#f8fafc',
                        border: '1px solid rgba(52, 211, 153, 0.24)',
                      }}
                    >
                      <Typography variant="body2" sx={{ color: '#0f172a', fontSize: '0.98rem', fontWeight: 700 }}>
                        {resource.title}
                      </Typography>
                      <Typography variant="body2" sx={{ mt: 0.65, color: '#475569', fontSize: '0.93rem', lineHeight: 1.7 }}>
                        {resource.category} · {resource.reason}
                      </Typography>
                    </Box>
                  ))}
                </Stack>
              ) : (
                <Box
                  sx={{
                    p: 1.35,
                    borderRadius: 2,
                    bgcolor: '#f8fafc',
                    border: '1px solid rgba(52, 211, 153, 0.24)',
                  }}
                >
                  <Typography variant="body2" sx={{ color: '#1e293b', fontSize: '0.96rem', lineHeight: 1.75 }}>
                    完成几轮有效作答后，这里会根据你的短板推荐针对性的学习资源。
                  </Typography>
                </Box>
              )}
            </Paper>
          </Stack>
        </Box>
      </Box>
    </Box>
  );
};

export default Chat;
