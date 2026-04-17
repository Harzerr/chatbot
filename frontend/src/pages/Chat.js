import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { jsPDF } from 'jspdf';
import {
  Box,
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
import { useAuth } from '../contexts/AuthContext';
import chatService from '../services/chatService';
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

const getElapsedInterviewMinutes = (startedAt, endedAt = null, fallbackNow = Date.now()) => {
  const startTime = startedAt ? new Date(startedAt).getTime() : Number.NaN;
  const endTime = endedAt ? new Date(endedAt).getTime() : fallbackNow;

  if (Number.isNaN(startTime) || Number.isNaN(endTime) || endTime <= startTime) {
    return 0;
  }

  return Math.max(1, Math.ceil((endTime - startTime) / 60000));
};

const formatMinuteAmount = (minutes) => {
  if (!minutes) return '< 1 分钟';
  return `${minutes} 分钟`;
};

const buildInterviewTimeCopy = (meta = {}, now = Date.now()) => {
  const estimatedMinutes = meta.estimatedMinutes || getEstimatedInterviewMinutes(meta.interviewType);
  const elapsedMinutes = getElapsedInterviewMinutes(meta.startedAt, meta.endedAt, now);

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

  return {
    short: `已用 ${formatMinuteAmount(elapsedMinutes)}`,
    detail: `已用 ${formatMinuteAmount(elapsedMinutes)} · 预计 ${estimatedMinutes} 分钟`,
  };
};

const escapeHtml = (content = '') => String(content)
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#39;');

const renderListHtml = (items = [], emptyText = '暂无内容') => {
  if (!items.length) {
    return `<p class="empty-state">${escapeHtml(emptyText)}</p>`;
  }

  return `
    <ul class="report-list">
      ${items.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}
    </ul>
  `;
};

const renderResourcesHtml = (resources = []) => {
  if (!resources.length) {
    return '<p class="empty-state">暂无推荐资源</p>';
  }

  return resources.map((resource) => `
    <div class="resource-card">
      <h4>${escapeHtml(resource.title)}</h4>
      <p>${escapeHtml(resource.category)} · ${escapeHtml(resource.reason)}</p>
    </div>
  `).join('');
};

const renderInterviewQuestionsHtml = (questions = []) => {
  if (!questions.length) {
    return '<p class="empty-state">暂无可展示的面试问答记录。</p>';
  }

  return questions.map((item, index) => `
    <div class="qa-item">
      <p class="qa-label">第 ${index + 1} 题 · 面试官问题</p>
      <p class="qa-content">${escapeHtml(item.question || '未记录问题')}</p>
      <p class="qa-label">候选人回答</p>
      <p class="qa-content">${escapeHtml(item.candidate_answer || '未记录回答')}</p>
      <p class="qa-label">参考答案</p>
      <p class="qa-content">${escapeHtml(item.reference_answer || '暂无参考答案')}</p>
    </div>
  `).join('');
};

const getEffectiveAnswerCount = (reportData = {}) => {
  const scoredCount = Number(reportData?.total_answers || 0);
  const qaCount = Array.isArray(reportData?.interview_questions)
    ? reportData.interview_questions.filter((item) => String(item?.candidate_answer || '').trim()).length
    : 0;
  return Math.max(scoredCount, qaCount);
};

const formatReportTime = (dateInput = new Date()) => new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
}).format(dateInput);

const toSafeFileNamePart = (value = '') => value.replace(/[\\/:*?"<>|]/g, '-').trim();

const buildReportFileName = (chatMeta, reportData) => {
  const role = toSafeFileNamePart(reportData?.interview_role || chatMeta?.role || '通用软件工程师');
  const interviewType = toSafeFileNamePart(reportData?.interview_type || chatMeta?.interviewType || '一面');
  const timestamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\..+$/, '');
  return `${role}-${interviewType}-面试报告-${timestamp}.pdf`;
};

const PDF_CN_FONT_NAME = 'SimHeiCN';
let pdfCnFontPromise = null;

const blobToBase64 = (blob) => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => {
    const result = typeof reader.result === 'string' ? reader.result : '';
    const base64 = result.includes(',') ? result.split(',')[1] : result;
    resolve(base64);
  };
  reader.onerror = reject;
  reader.readAsDataURL(blob);
});

const loadPdfChineseFontData = async () => {
  if (!pdfCnFontPromise) {
    pdfCnFontPromise = (async () => {
      const candidates = ['/fonts/simhei.ttf', '/fonts/NotoSansSC-VF.ttf'];
      for (const url of candidates) {
        try {
          const response = await fetch(url);
          if (!response.ok) continue;
          const blob = await response.blob();
          const base64 = await blobToBase64(blob);
          const fileName = url.split('/').pop() || 'simhei.ttf';
          if (!base64) continue;
          return { fileName, base64 };
        } catch (error) {
          // try next candidate
        }
      }
      return null;
    })();
  }
  return pdfCnFontPromise;
};

const buildReportPrintHtml = (chatMeta, reportData) => {
  const fileName = buildReportFileName(chatMeta, reportData);
  const scoreCards = [
    { label: '综合得分', value: reportData.overall_score, tone: '#0ea5e9' },
    { label: '技术准确性', value: reportData.technical_accuracy, tone: '#64748b' },
    { label: '知识深度', value: reportData.knowledge_depth, tone: '#f59e0b' },
    { label: '表达清晰度', value: reportData.communication_clarity, tone: '#22c55e' },
    { label: '逻辑结构', value: reportData.logical_structure, tone: '#8b5cf6' },
    { label: '问题解决', value: reportData.problem_solving, tone: '#ec4899' },
    { label: '岗位匹配度', value: reportData.job_match_score, tone: '#14b8a6' },
  ];

  return `
    <!DOCTYPE html>
    <html lang="zh-CN">
      <head>
        <meta charset="utf-8" />
        <title>${escapeHtml(fileName)}</title>
        <style>
          @page {
            size: A4;
            margin: 14mm;
          }

          * {
            box-sizing: border-box;
          }

          body {
            margin: 0;
            font-family: "PingFang SC", "Microsoft YaHei", "Noto Sans SC", sans-serif;
            color: #0f172a;
            background: #f8fafc;
            overflow-wrap: anywhere;
            word-break: break-word;
          }

          .page {
            padding: 24px;
            overflow-wrap: anywhere;
          }

          .hero {
            padding: 28px;
            border-radius: 18px;
            color: #e2e8f0;
            background: linear-gradient(135deg, #082f49 0%, #0f172a 100%);
          }

          .hero h1 {
            margin: 0 0 12px;
            font-size: 28px;
          }

          .hero p {
            margin: 0;
            color: rgba(226, 232, 240, 0.82);
            line-height: 1.7;
            font-size: 14px;
          }

          .meta-grid,
          .score-grid,
          .section-grid {
            display: grid;
            gap: 14px;
          }

          .meta-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
            margin-top: 18px;
          }

          .score-grid {
            grid-template-columns: repeat(3, minmax(0, 1fr));
            margin: 22px 0;
          }

          .section-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }

          .card {
            border-radius: 16px;
            background: #ffffff;
            border: 1px solid #dbe4f0;
            padding: 18px;
            break-inside: avoid;
          }

          .meta-item span,
          .card-label {
            display: block;
            font-size: 12px;
            letter-spacing: 0.04em;
            color: #64748b;
            margin-bottom: 8px;
          }

          .meta-item strong,
          .score-value {
            font-size: 18px;
            color: #0f172a;
          }

          .score-card {
            border-radius: 16px;
            padding: 18px;
            color: #ffffff;
          }

          .score-value {
            display: block;
            margin-top: 12px;
            font-size: 30px;
            font-weight: 700;
            color: #ffffff;
          }

          .section-title {
            margin: 0 0 12px;
            font-size: 18px;
            color: #0f172a;
          }

          .summary {
            margin: 0;
            line-height: 1.9;
            font-size: 14px;
            color: #1e293b;
            white-space: pre-wrap;
            overflow-wrap: anywhere;
            word-break: break-word;
          }

          .report-list {
            margin: 0;
            padding-left: 20px;
          }

          .report-list li {
            margin: 0 0 10px;
            color: #334155;
            line-height: 1.8;
            font-size: 14px;
            overflow-wrap: anywhere;
            word-break: break-word;
          }

          .resource-card {
            border-radius: 14px;
            padding: 14px 16px;
            background: #f8fafc;
            border: 1px solid #dbe4f0;
            margin-bottom: 12px;
          }

          .resource-card h4 {
            margin: 0 0 8px;
            font-size: 15px;
            color: #0f172a;
            overflow-wrap: anywhere;
            word-break: break-word;
          }

          .resource-card p,
          .empty-state {
            margin: 0;
            line-height: 1.8;
            font-size: 14px;
            color: #475569;
            overflow-wrap: anywhere;
            word-break: break-word;
          }

          .qa-item {
            border-radius: 14px;
            padding: 14px 16px;
            background: #f8fafc;
            border: 1px solid #dbe4f0;
            margin-bottom: 12px;
          }

          .qa-label {
            margin: 0 0 8px;
            color: #475569;
            font-size: 12px;
            letter-spacing: 0.04em;
          }

          .qa-content {
            margin: 0 0 14px;
            color: #0f172a;
            line-height: 1.85;
            font-size: 14px;
            white-space: pre-wrap;
            overflow-wrap: anywhere;
            word-break: break-word;
          }

          .qa-item .qa-content:last-child {
            margin-bottom: 0;
          }

          .footer {
            margin-top: 22px;
            font-size: 12px;
            color: #64748b;
            text-align: right;
          }

          @media print {
            body {
              background: #ffffff;
            }

            .page {
              padding: 0;
            }
          }
        </style>
      </head>
      <body>
        <div class="page">
          <section class="hero">
            <h1>${escapeHtml(reportData.interview_role || chatMeta?.role || '通用软件工程师')} 面试报告</h1>
            <p>${escapeHtml(reportData.summary || '当前有效回答样本不足，暂时无法生成完整评估报告。')}</p>
          </section>

          <section class="meta-grid">
            <div class="card meta-item">
              <span>面试级别</span>
              <strong>${escapeHtml(reportData.interview_level || chatMeta?.level || '中级')}</strong>
            </div>
            <div class="card meta-item">
              <span>面试类型</span>
              <strong>${escapeHtml(reportData.interview_type || chatMeta?.interviewType || '一面')}</strong>
            </div>
            <div class="card meta-item">
              <span>目标公司</span>
              <strong>${escapeHtml(reportData.target_company || chatMeta?.targetCompany || '未设置')}</strong>
            </div>
            <div class="card meta-item">
              <span>有效作答轮次</span>
              <strong>${escapeHtml(String(getEffectiveAnswerCount(reportData)))}</strong>
            </div>
          </section>

          <section class="score-grid">
            ${scoreCards.map((item) => `
              <div class="score-card" style="background: linear-gradient(135deg, ${item.tone} 0%, #0f172a 180%);">
                <span class="card-label">${escapeHtml(item.label)}</span>
                <strong class="score-value">${escapeHtml(String(item.value ?? 0))}</strong>
              </div>
            `).join('')}
          </section>

          <section class="card" style="margin-bottom: 14px;">
            <h2 class="section-title">综合总结</h2>
            <p class="summary">${escapeHtml(reportData.summary || '暂无总结。')}</p>
          </section>

          <section class="card" style="margin-bottom: 14px;">
            <h2 class="section-title">内容分析</h2>
            <p class="summary">${escapeHtml(reportData.content_analysis || '暂无内容分析。')}</p>
          </section>

          <section class="card" style="margin-bottom: 14px;">
            <h2 class="section-title">面试问答记录与参考答案</h2>
            ${renderInterviewQuestionsHtml(reportData.interview_questions)}
          </section>

          <section class="section-grid">
            <div class="card">
              <h2 class="section-title">优势亮点</h2>
              ${renderListHtml(reportData.strengths, '暂无明显优势项')}
            </div>
            <div class="card">
              <h2 class="section-title">待提升项</h2>
              ${renderListHtml(reportData.improvement_areas, '暂无明显短板')}
            </div>
            <div class="card">
              <h2 class="section-title">后续建议</h2>
              ${renderListHtml(reportData.recommendations, '暂无建议')}
            </div>
            <div class="card">
              <h2 class="section-title">推荐资源</h2>
              ${renderResourcesHtml(reportData.recommended_resources)}
            </div>
          </section>

          <p class="footer">导出时间：${escapeHtml(formatReportTime(new Date()))}</p>
        </div>
      </body>
    </html>
  `;
};

const downloadReportPdf = async (chatMeta, reportData) => {
  const fileName = buildReportFileName(chatMeta, reportData);
  void buildReportPrintHtml(chatMeta, reportData);
  const pdf = new jsPDF({ orientation: 'portrait', unit: 'pt', format: 'a4' });
  const pageWidth = pdf.internal.pageSize.getWidth();
  const pageHeight = pdf.internal.pageSize.getHeight();
  const marginX = 40;
  const marginY = 40;
  const contentWidth = pageWidth - marginX * 2;
  const contentBottom = pageHeight - marginY;
  const bodyLineHeight = 14.5;
  const qaLineHeight = 13.5;

  let currentY = marginY;
  let pageNumber = 1;
  let chineseFontReady = false;

  try {
    const fontData = await loadPdfChineseFontData();
    if (fontData) {
      const fontList = pdf.getFontList?.() || {};
      if (!fontList[PDF_CN_FONT_NAME]) {
        const alreadyInVfs = typeof pdf.existsFileInVFS === 'function'
          ? pdf.existsFileInVFS(fontData.fileName)
          : false;
        if (!alreadyInVfs) {
          pdf.addFileToVFS(fontData.fileName, fontData.base64);
        }
        pdf.addFont(fontData.fileName, PDF_CN_FONT_NAME, 'normal');
        pdf.addFont(fontData.fileName, PDF_CN_FONT_NAME, 'bold');
      }
      chineseFontReady = true;
    }
  } catch (error) {
    console.warn('Failed to load Chinese PDF font, fallback to default font:', error);
  }

  const setPdfFont = (style = 'normal') => {
    if (chineseFontReady) {
      pdf.setFont(PDF_CN_FONT_NAME, style);
    } else {
      pdf.setFont('helvetica', style);
    }
  };

  const toText = (value, fallback = '') => {
    const normalized = String(value ?? '').trim();
    return normalized || fallback;
  };

  const splitLines = (text, width) => pdf.splitTextToSize(toText(text), width);

  const drawPageFooter = () => {
    setPdfFont('normal');
    pdf.setFontSize(9);
    pdf.setTextColor(148, 163, 184);
    pdf.text(`第 ${pageNumber} 页`, pageWidth - marginX, pageHeight - 20, { align: 'right' });
  };

  const nextPage = () => {
    drawPageFooter();
    pdf.addPage();
    pageNumber += 1;
    currentY = marginY;
  };

  const ensureSpace = (heightNeeded) => {
    if (currentY + heightNeeded > contentBottom) {
      nextPage();
    }
  };

  const drawHeading = (title) => {
    ensureSpace(24);
    setPdfFont('bold');
    pdf.setFontSize(16);
    pdf.setTextColor(15, 23, 42);
    pdf.text(title, marginX, currentY);
    currentY += 22;
  };

  const drawParagraph = (text, options = {}) => {
    const {
      fontSize = 11,
      textColor = [51, 65, 85],
      lineHeight = bodyLineHeight,
      maxLines = null,
      spacingAfter = 10,
    } = options;
    const lines = splitLines(text, contentWidth);
    const displayLines = maxLines && lines.length > maxLines
      ? [...lines.slice(0, maxLines - 1), `${lines[maxLines - 1]} ...`]
      : lines;

    ensureSpace(displayLines.length * lineHeight + spacingAfter);
    setPdfFont('normal');
    pdf.setFontSize(fontSize);
    pdf.setTextColor(...textColor);
    displayLines.forEach((line) => {
      pdf.text(line, marginX, currentY);
      currentY += lineHeight;
    });
    currentY += spacingAfter;
  };

  const drawMetaLine = (label, value) => {
    const lines = splitLines(`${label}：${toText(value, '未设置')}`, contentWidth);
    ensureSpace(lines.length * bodyLineHeight + 4);
    setPdfFont('normal');
    pdf.setFontSize(11);
    pdf.setTextColor(51, 65, 85);
    lines.forEach((line) => {
      pdf.text(line, marginX, currentY);
      currentY += bodyLineHeight;
    });
    currentY += 4;
  };

  const drawBulletList = (title, items = [], fallbackText = '暂无', options = {}) => {
    const {
      maxItems = Number.MAX_SAFE_INTEGER,
      maxLinesPerItem = Number.MAX_SAFE_INTEGER,
    } = options;

    drawHeading(title);
    const displayItems = (items.length ? items : [fallbackText]).slice(0, maxItems);
    displayItems.forEach((item, index) => {
      const bulletPrefix = `${index + 1}. `;
      const lines = splitLines(toText(item, fallbackText), contentWidth - 18);
      const clippedLines = lines.length > maxLinesPerItem
        ? [...lines.slice(0, maxLinesPerItem - 1), `${lines[maxLinesPerItem - 1]} ...`]
        : lines;
      const blockHeight = clippedLines.length * bodyLineHeight + 4;
      ensureSpace(blockHeight);

      setPdfFont('normal');
      pdf.setFontSize(11);
      pdf.setTextColor(51, 65, 85);
      pdf.text(bulletPrefix, marginX, currentY);
      clippedLines.forEach((line, lineIndex) => {
        pdf.text(line, marginX + 16, currentY + lineIndex * bodyLineHeight);
      });
      currentY += clippedLines.length * bodyLineHeight + 4;
    });
    currentY += 6;
  };

  const drawResourceList = (resources = []) => {
    drawHeading('推荐资源');
    if (!resources.length) {
      drawParagraph('暂无推荐资源。', { spacingAfter: 6 });
      return;
    }

    resources.slice(0, 3).forEach((resource, index) => {
      const title = toText(resource?.title, `资源 ${index + 1}`);
      const detail = `${toText(resource?.category, '类别未设置')}：${toText(resource?.reason, '暂无推荐理由')}`;

      setPdfFont('bold');
      pdf.setFontSize(11);
      pdf.setTextColor(15, 23, 42);
      const titleLines = splitLines(`${index + 1}. ${title}`, contentWidth);
      ensureSpace(titleLines.length * bodyLineHeight + 4);
      titleLines.forEach((line) => {
        pdf.text(line, marginX, currentY);
        currentY += bodyLineHeight;
      });

      drawParagraph(detail, {
        fontSize: 10.5,
        textColor: [71, 85, 105],
        maxLines: 2,
        spacingAfter: 6,
      });
    });
  };

  const fitQaBlockLines = (questionLines, answerLines, referenceLines) => {
    const maxBlockHeight = contentBottom - marginY;
    const blockPadding = 12;
    const sectionGap = 8;
    const sectionLabelHeight = 14;
    const sectionHeight = (lines) => sectionLabelHeight + lines.length * qaLineHeight;

    const calculateHeight = () => (
      blockPadding * 2
      + sectionHeight(questionLines)
      + sectionGap
      + sectionHeight(answerLines)
      + sectionGap
      + sectionHeight(referenceLines)
    );

    let blockHeight = calculateHeight();
    const truncated = {
      question: false,
      answer: false,
      reference: false,
    };

    while (blockHeight > maxBlockHeight) {
      const candidates = [
        { key: 'answer', length: answerLines.length },
        { key: 'reference', length: referenceLines.length },
        { key: 'question', length: questionLines.length },
      ].sort((a, b) => b.length - a.length);

      let reduced = false;
      for (const candidate of candidates) {
        if (candidate.key === 'answer' && answerLines.length > 2) {
          answerLines = answerLines.slice(0, -1);
          truncated.answer = true;
          reduced = true;
          break;
        }
        if (candidate.key === 'reference' && referenceLines.length > 2) {
          referenceLines = referenceLines.slice(0, -1);
          truncated.reference = true;
          reduced = true;
          break;
        }
        if (candidate.key === 'question' && questionLines.length > 2) {
          questionLines = questionLines.slice(0, -1);
          truncated.question = true;
          reduced = true;
          break;
        }
      }

      if (!reduced) break;
      blockHeight = calculateHeight();
    }

    if (truncated.question && questionLines.length) {
      questionLines[questionLines.length - 1] = `${questionLines[questionLines.length - 1]} ...`;
    }
    if (truncated.answer && answerLines.length) {
      answerLines[answerLines.length - 1] = `${answerLines[answerLines.length - 1]} ...`;
    }
    if (truncated.reference && referenceLines.length) {
      referenceLines[referenceLines.length - 1] = `${referenceLines[referenceLines.length - 1]} ...`;
    }

    return {
      questionLines,
      answerLines,
      referenceLines,
      blockHeight,
    };
  };

  const drawQaBlock = (item, index) => {
    const blockPadding = 12;
    const sectionGap = 8;
    const innerX = marginX + blockPadding;
    const innerWidth = contentWidth - blockPadding * 2;
    const titleLineHeight = 14;

    const rawQuestionLines = splitLines(toText(item.question, '未记录问题'), innerWidth);
    const rawAnswerLines = splitLines(toText(item.candidate_answer, '未记录回答'), innerWidth);
    const rawReferenceLines = splitLines(toText(item.reference_answer, '暂无参考答案'), innerWidth);

    const {
      questionLines,
      answerLines,
      referenceLines,
      blockHeight,
    } = fitQaBlockLines(rawQuestionLines, rawAnswerLines, rawReferenceLines);

    ensureSpace(blockHeight + 10);
    pdf.setFillColor(248, 250, 252);
    pdf.setDrawColor(203, 213, 225);
    pdf.roundedRect(marginX, currentY, contentWidth, blockHeight, 7, 7, 'FD');

    let cursorY = currentY + blockPadding;

    const drawQaSection = (label, lines) => {
      setPdfFont('bold');
      pdf.setFontSize(10);
      pdf.setTextColor(71, 85, 105);
      pdf.text(label, innerX, cursorY + 10);
      cursorY += titleLineHeight;

      setPdfFont('normal');
      pdf.setFontSize(10.5);
      pdf.setTextColor(15, 23, 42);
      lines.forEach((line) => {
        pdf.text(line, innerX, cursorY + 10);
        cursorY += qaLineHeight;
      });
    };

    drawQaSection(`第 ${index + 1} 题 · 面试官问题`, questionLines);
    cursorY += sectionGap;
    drawQaSection('候选人回答', answerLines);
    cursorY += sectionGap;
    drawQaSection('参考答案', referenceLines);

    currentY += blockHeight + 10;
  };

  const role = toText(reportData.interview_role || chatMeta?.role, '通用软件工程师');
  const level = toText(reportData.interview_level || chatMeta?.level, '中级');
  const interviewType = toText(reportData.interview_type || chatMeta?.interviewType, '一面');
  const company = toText(reportData.target_company || chatMeta?.targetCompany, '未设置');

  drawHeading(`${role} 面试报告`);
  drawMetaLine('导出时间', formatReportTime(new Date()));
  drawMetaLine('面试级别', level);
  drawMetaLine('面试类型', interviewType);
  drawMetaLine('目标公司', company);
  drawMetaLine('有效作答轮次', String(getEffectiveAnswerCount(reportData)));

  drawHeading('面试评价');
  drawMetaLine('综合得分', String(reportData.overall_score ?? 0));
  drawMetaLine('技术准确性', String(reportData.technical_accuracy ?? 0));
  drawMetaLine('知识深度', String(reportData.knowledge_depth ?? 0));
  drawMetaLine('表达清晰度', String(reportData.communication_clarity ?? 0));
  drawMetaLine('逻辑结构', String(reportData.logical_structure ?? 0));
  drawMetaLine('问题解决', String(reportData.problem_solving ?? 0));
  drawMetaLine('岗位匹配度', String(reportData.job_match_score ?? 0));

  drawHeading('综合总结');
  drawParagraph(toText(reportData.summary, '暂无总结。'), { maxLines: 6 });

  drawHeading('内容分析');
  drawParagraph(toText(reportData.content_analysis, '暂无内容分析。'), { maxLines: 6 });

  drawBulletList('优势亮点', reportData.strengths || [], '暂无明显优势项', {
    maxItems: 3,
    maxLinesPerItem: 2,
  });
  drawBulletList('待提升项', reportData.improvement_areas || [], '暂无明显短板', {
    maxItems: 3,
    maxLinesPerItem: 2,
  });
  drawBulletList('后续建议', reportData.recommendations || [], '暂无建议', {
    maxItems: 3,
    maxLinesPerItem: 2,
  });
  drawResourceList(reportData.recommended_resources || []);

  // 强制问答记录从第二页开始
  nextPage();

  drawHeading('面试问答记录与参考答案');
  const interviewQuestions = Array.isArray(reportData.interview_questions)
    ? reportData.interview_questions
    : [];

  if (!interviewQuestions.length) {
    drawParagraph('暂无可展示的面试问答记录。', {
      fontSize: 11,
      textColor: [71, 85, 105],
      spacingAfter: 0,
    });
  } else {
    interviewQuestions.forEach((item, index) => {
      drawQaBlock(item, index);
    });
  }

  drawPageFooter();
  pdf.save(fileName);
};

const getLatestEvaluation = (messages = []) => (
  [...messages]
    .sort((a, b) => (getMessageTimestamp(b) || 0) - (getMessageTimestamp(a) || 0))
    .find((message) => message.evaluation)?.evaluation || null
);

const deriveInterviewMeta = (chat) => {
  const latestEvaluation = getLatestEvaluation(chat.messages);

  if (chat.interviewRole || chat.interviewLevel || chat.interviewType) {
    const questionCount = Math.max(1, Math.ceil((chat.messages?.length || 1) / 2));
    const interviewType = chat.interviewType || '一面';
    const startedAt = getInterviewStartedAt(chat);
    const endedAt = getInterviewEndedAt(chat);
    const isFinished = !!endedAt;
    const status = isFinished ? '已完成' : chat.status || '进行中';
    const estimatedMinutes = getEstimatedInterviewMinutes(interviewType);
    return {
      role: chat.interviewRole || '通用软件工程师',
      level: chat.interviewLevel || '中级',
      interviewType,
      targetCompany: chat.targetCompany || '',
      score: latestEvaluation?.overall_score ?? null,
      status,
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
  const questionCount = Math.max(1, Math.ceil((chat.messages?.length || 1) / 2));
  const targetQuestions = getInterviewQuestionLimit(interviewType);
  const isFinished = hasInterviewEnded(chat.messages || []);
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
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [setupDialogOpen, setSetupDialogOpen] = useState(false);
  const [resumePromptOpen, setResumePromptOpen] = useState(false);
  const [report, setReport] = useState(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [finishExportLoading, setFinishExportLoading] = useState(false);
  const [finishRequestedAt, setFinishRequestedAt] = useState(null);
  const [timeNow, setTimeNow] = useState(() => Date.now());
  const [interviewSetup, setInterviewSetup] = useState({
    interviewRole: 'Web前端工程师',
    interviewLevel: '中级',
    interviewType: '一面',
    targetCompany: '',
    jdContent: '',
  });

  const isInterviewFinished = (messageList = messages) => {
    return hasInterviewEnded(messageList);
  };

  const messagesEndRef = useRef(null);
  const currentChatIdRef = useRef(null);
  const reportRequestIdRef = useRef(0);
  const { logout, currentUser } = useAuth();
  const navigate = useNavigate();
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('lg'));

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingMessage]);

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
    if (!roleOptions.includes(currentUser.target_role)) return;

    setInterviewSetup((prev) => ({
      ...prev,
      interviewRole: currentUser.target_role,
    }));
  }, [currentUser]);

  const clearReportState = () => {
    reportRequestIdRef.current += 1;
    setReportLoading(false);
    setReport(null);
  };

  const fetchInterviewReport = async (chatId, options = {}) => {
    const { rethrow = false } = options;
    const requestId = reportRequestIdRef.current + 1;
    reportRequestIdRef.current = requestId;
    setReportLoading(true);
    try {
      const response = await chatService.getInterviewReport(chatId);
      if (requestId !== reportRequestIdRef.current) {
        return null;
      }
      if (!currentChatIdRef.current || currentChatIdRef.current === chatId) {
        setReport(response);
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
      if (requestId === reportRequestIdRef.current) {
        setReportLoading(false);
      }
    }
  };

  const fetchChats = async () => {
    setLoading(true);
    setError(null);

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
        };
        const meta = deriveInterviewMeta(baseChat);
        return { ...baseChat, ...meta };
      });

      const sortedChats = chatList.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
      setChats(sortedChats);
      setCurrentChat((prev) => {
        if (!prev) return prev;
        return sortedChats.find((chat) => chat.id === prev.id) || prev;
      });

      if (sortedChats.length > 0 && !currentChat) {
        handleSelectChat(sortedChats[0].id, sortedChats);
      }
    } catch (err) {
      console.error('Error fetching chats:', err);
      setError('加载面试会话失败，请稍后重试。');
    } finally {
      setLoading(false);
    }
  };

  const fetchMessages = async (chatId) => {
    setChatLoading(true);
    setError(null);
    clearReportState();

    try {
      const response = await chatService.getChatById(chatId);
      const sortedMessages = [...response.messages].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));

      const formattedMessages = sortedMessages
        .flatMap((msg) => {
          const formattedThread = [];

          if (!isManualFinishCommand(msg.user_message)) {
            formattedThread.push({
              id: msg.id,
              content: msg.user_message,
              role: 'user',
              timestamp: msg.timestamp,
              evaluation: msg.evaluation,
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
        });

      setMessages(formattedMessages);
      if (formattedMessages.some((message) => message.role === 'assistant' && includesInterviewEndMarker(message.content))) {
        fetchInterviewReport(chatId);
      }
    } catch (err) {
      console.error(`Error fetching messages for chat ${chatId}:`, err);
      setError('加载面试记录失败，请稍后重试。');
    } finally {
      setChatLoading(false);
    }
  };

  const handleSelectChat = (chatId, sourceChats = chats) => {
    const selected = sourceChats.find((chat) => chat.id === chatId);

    if (selected) {
      setFinishRequestedAt(null);
      setCurrentChat(selected);
      fetchMessages(chatId);

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
    const createdChat = createInterviewSession(interviewSetup);
    setSetupDialogOpen(false);
    startInterviewOpening(createdChat);
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
          fetchChats();
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
      });
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
          fetchChats();
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

  const handleExportReport = async () => {
    if (!currentChat?.id || isStreaming || finishExportLoading) return;

    setFinishExportLoading(true);
    setError(null);

    try {
      const latestReport = report || await fetchInterviewReport(currentChat.id, { rethrow: true });
      if (!latestReport) {
        throw new Error('生成面试报告失败，请稍后重试。');
      }

      await downloadReportPdf(currentChat, latestReport);
    } catch (exportError) {
      console.error('Error exporting interview report:', exportError);
      setError(exportError.message || '导出报告失败，请稍后重试。');
    } finally {
      setFinishExportLoading(false);
    }
  };

  const handleReportAction = () => {
    if (isInterviewFinished()) {
      handleExportReport();
      return;
    }

    handleFinishInterview();
  };

  const handleSendMessage = async (message) => {
    if (!message.trim() || isStreaming || isInterviewFinished()) return;
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
          fetchChats();
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

  const handleRunCode = async ({ language, sourceCode, stdin, expectedOutput }) => {
    const response = await chatService.runCode({
      language,
      sourceCode,
      stdin,
      expectedOutput,
    });
    return response;
  };

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const assistantQuestionCount = messages.filter((m) => m.role === 'assistant').length;
  const currentInterviewFinished = isInterviewFinished();
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

      {loading ? (
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
              <Typography variant="subtitle2" sx={{ color: '#f8fafc' }}>
                还没有面试记录
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                从第一场模拟面试开始，逐步建立你的练习记录。
              </Typography>
            </Paper>
          ) : (
            chats.map((chat) => (
              <ListItem key={chat.id} disablePadding sx={{ mb: 1.2 }}>
                <ListItemButton
                  selected={currentChat?.id === chat.id}
                  onClick={() => handleSelectChat(chat.id)}
                  sx={{
                    borderRadius: 2,
                    px: 2,
                    py: 1.8,
                    alignItems: 'flex-start',
                    border: currentChat?.id === chat.id
                      ? '1px solid rgba(125,211,252,0.24)'
                      : '1px solid rgba(148,163,184,0.08)',
                    bgcolor: currentChat?.id === chat.id
                      ? 'rgba(125,211,252,0.08)'
                      : 'rgba(15,23,42,0.55)',
                  }}
                >
                  <Box sx={{ width: '100%' }}>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 0.5, mb: 0.6 }}>
                      <Typography variant="subtitle2" sx={{ color: '#f8fafc' }}>
                        {chat.title}
                      </Typography>
                      <Typography variant="body2" sx={{ color: '#cbd5e1' }}>
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
                        color: 'rgba(226,232,240,0.64)',
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
        open={resumePromptOpen}
        onClose={() => setResumePromptOpen(false)}
        fullWidth
        maxWidth="xs"
        PaperProps={{
          sx: {
            borderRadius: 2.5,
            background: 'linear-gradient(180deg, rgba(13,23,40,0.96) 0%, rgba(8,15,28,0.98) 100%)',
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
          <Button onClick={() => setResumePromptOpen(false)} sx={{ color: '#cbd5e1' }}>
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
            background: 'linear-gradient(180deg, rgba(13,23,40,0.96) 0%, rgba(8,15,28,0.98) 100%)',
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
                border: '1px solid rgba(125,211,252,0.12)',
              }}
            >
              <Typography variant="subtitle2" sx={{ color: '#f8fafc' }}>
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
              label="目标岗位"
              value={interviewSetup.interviewRole}
              onChange={(e) => setInterviewSetup((prev) => ({ ...prev, interviewRole: e.target.value }))}
            >
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
              <Typography variant="subtitle2" sx={{ color: '#f8fafc' }}>
                本场节奏
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75, lineHeight: 1.7 }}>
                {interviewSetup.interviewType}预计 {getEstimatedInterviewMinutes(interviewSetup.interviewType)} 分钟，约 {getInterviewQuestionLimit(interviewSetup.interviewType)} 道题。系统会根据你的回答继续追问，实际用时会随作答深度浮动。
              </Typography>
            </Paper>

            <TextField
              fullWidth
              multiline
              minRows={4}
              maxRows={8}
              label="JD 内容"
              placeholder="可粘贴岗位职责、要求、加分项。没有也可以留空。"
              value={interviewSetup.jdContent}
              onChange={(e) => setInterviewSetup((prev) => ({ ...prev, jdContent: e.target.value }))}
            />
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 4, pb: 4, pt: 2 }}>
          <Button onClick={() => setSetupDialogOpen(false)} sx={{ color: '#cbd5e1' }}>
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
            <Chip icon={<WorkOutlineRoundedIcon />} label={currentMeta.role} sx={{ bgcolor: 'rgba(125,211,252,0.10)', color: '#7dd3fc' }} />
            <Chip icon={<TrackChangesRoundedIcon />} label={`第 ${Math.max(1, assistantQuestionCount)} / ${currentMeta.targetQuestions} 题`} sx={{ bgcolor: 'rgba(245,158,11,0.10)', color: '#fbbf24' }} />
            <Chip icon={<ScheduleRoundedIcon />} label={currentTimeCopy.short} sx={{ bgcolor: 'rgba(148,163,184,0.12)', color: '#cbd5e1' }} />
          </Stack>

          <Button color="inherit" onClick={() => navigate('/profile')} startIcon={<AccountCircleRoundedIcon />}>
            个人档案
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
            bgcolor: '#091321',
            borderRight: '1px solid rgba(125, 211, 252, 0.08)',
            backgroundImage:
              'linear-gradient(180deg, rgba(14,165,233,0.04) 0%, rgba(9,19,33,1) 100%)',
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
                  bgcolor: 'rgba(15,23,42,0.75)',
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
                  <MessageBubble key={message.id} content={message.content} role={message.role} />
                ))}

                {isStreaming && (
                  <MessageBubble content={streamingMessage} role="assistant" isStreaming />
                )}

                <div ref={messagesEndRef} />
              </>
            )}
          </Box>

          {(currentChat || messages.length > 0) && (
            <ChatInput
              onSendMessage={handleSendMessage}
              onRunCode={handleRunCode}
              latestCodingPrompt={latestCodingPrompt}
              disabled={isStreaming || isInterviewFinished()}
            />
          )}
        </Box>

        <Box
          sx={{
            display: { xs: 'none', lg: 'block' },
            p: 3,
            pt: 11,
            borderLeft: '1px solid rgba(125,211,252,0.08)',
            background: 'rgba(8,15,28,0.54)',
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
                bgcolor: 'rgba(15,23,42,0.72)',
                backgroundImage: 'linear-gradient(135deg, rgba(14,165,233,0.14) 0%, rgba(15,23,42,0.92) 60%)',
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
                      color: '#f8fafc',
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
                    color: '#7dd3fc',
                    borderRadius: 2,
                    whiteSpace: 'nowrap',
                    flexShrink: 0,
                    
                  }}
                >
                  {finishExportLoading || reportLoading
                    ? '处理中...'
                    : isInterviewFinished()
                      ? '导出报告PDF'
                      : '结束面试'}
                </Button>
               
              

                <Stack direction="row" spacing={0.8} useFlexGap flexWrap="wrap" alignItems="flex-start">
                  <Chip
                    size="small"
                    label={currentMeta.level}
                    sx={{
                      bgcolor: 'rgba(125,211,252,0.10)',
                      color: '#7dd3fc',
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
                      color: '#cbd5e1',
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
                      color: '#34d399',
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
                      color: '#cbd5e1',
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
                      color: '#fbbf24',
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
                  borderTop: '1px solid rgba(148,163,184,0.12)',
                }}
              >
                <Typography variant="subtitle2" sx={{ color: '#f8fafc', fontWeight: 700 }}>
                  报告摘要
                </Typography>
                {reportLoading ? (
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                    正在生成本场面试报告...
                  </Typography>
                ) : report ? (
                  <>
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                      {report.summary}
                    </Typography>
                    <Typography variant="caption" sx={{ mt: 0.6, display: 'block', color: 'rgba(191,219,254,0.9)' }}>
                      有效作答轮次：{getEffectiveAnswerCount(report)}
                    </Typography>
                  </>
                ) : (
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                    面试过程中不再逐轮展示评分。完成作答后，可在这里统一查看本场面试报告。
                  </Typography>
                )}
              </Box>
            </Paper>

            <Paper
              elevation={0}
              sx={{
                p: 2.5,
                borderRadius: 2.5,
                bgcolor: 'rgba(15,23,42,0.72)',
                backgroundImage: 'linear-gradient(180deg, rgba(147,197,253,0.08) 0%, rgba(15,23,42,0.78) 100%)',
              }}
            >
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.35 }}>
                <WorkOutlineRoundedIcon sx={{ color: '#93c5fd', fontSize: 20 }} />
                <Typography variant="subtitle1" sx={{ color: '#f8fafc', fontWeight: 700 }}>
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
                        bgcolor: 'rgba(255,255,255,0.04)',
                        border: '1px solid rgba(147,197,253,0.22)',
                      }}
                    >
                      <Typography variant="caption" sx={{ color: '#93c5fd', display: 'block', mb: 0.55 }}>
                        第 {index + 1} 题 · 面试官问题
                      </Typography>
                      <Typography variant="body2" sx={{ color: '#edf4ff', lineHeight: 1.7, mb: 1.1, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                        {item.question || '未记录问题'}
                      </Typography>

                      <Typography variant="caption" sx={{ color: 'rgba(191,219,254,0.9)', display: 'block', mb: 0.55 }}>
                        候选人回答
                      </Typography>
                      <Typography variant="body2" sx={{ color: 'rgba(226,232,240,0.86)', lineHeight: 1.7, mb: 1.1, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                        {item.candidate_answer || '未记录回答'}
                      </Typography>

                      <Typography variant="caption" sx={{ color: 'rgba(191,219,254,0.9)', display: 'block', mb: 0.55 }}>
                        参考答案
                      </Typography>
                      <Typography variant="body2" sx={{ color: 'rgba(226,232,240,0.86)', lineHeight: 1.7, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
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
                    bgcolor: 'rgba(255,255,255,0.04)',
                    border: '1px solid rgba(147,197,253,0.22)',
                  }}
                >
                  <Typography variant="body2" sx={{ color: '#edf4ff', fontSize: '0.96rem', lineHeight: 1.75 }}>
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
                bgcolor: 'rgba(15,23,42,0.72)',
                backgroundImage: 'linear-gradient(180deg, rgba(56,189,248,0.08) 0%, rgba(15,23,42,0.78) 100%)',
              }}
            >
              <Typography variant="subtitle1" sx={{ color: '#f8fafc', mb: 1.5, fontWeight: 700 }}>
                能力评估
              </Typography>
              {evaluationDisplay ? (
                <Stack spacing={1}>
                  <Chip icon={<AssignmentTurnedInRoundedIcon />} label={`技术准确性：${evaluationDisplay.technical_accuracy}`} sx={{ justifyContent: 'flex-start', bgcolor: 'rgba(148,163,184,0.08)', color: '#cbd5e1' }} />
                  <Chip icon={<AutoGraphRoundedIcon />} label={`知识深度：${evaluationDisplay.knowledge_depth}`} sx={{ justifyContent: 'flex-start', bgcolor: 'rgba(148,163,184,0.08)', color: '#cbd5e1' }} />
                  <Chip icon={<TipsAndUpdatesRoundedIcon />} label={`表达清晰度：${evaluationDisplay.communication_clarity}`} sx={{ justifyContent: 'flex-start', bgcolor: 'rgba(148,163,184,0.08)', color: '#cbd5e1' }} />
                  <Chip icon={<AssignmentTurnedInRoundedIcon />} label={`逻辑结构：${evaluationDisplay.logical_structure}`} sx={{ justifyContent: 'flex-start', bgcolor: 'rgba(148,163,184,0.08)', color: '#cbd5e1' }} />
                  <Chip icon={<AutoGraphRoundedIcon />} label={`问题解决：${evaluationDisplay.problem_solving}`} sx={{ justifyContent: 'flex-start', bgcolor: 'rgba(148,163,184,0.08)', color: '#cbd5e1' }} />
                  <Chip icon={<TrackChangesRoundedIcon />} label={`岗位匹配度：${evaluationDisplay.job_match_score ?? 0}`} sx={{ justifyContent: 'flex-start', bgcolor: 'rgba(148,163,184,0.08)', color: '#cbd5e1' }} />
                  <Chip icon={<TipsAndUpdatesRoundedIcon />} label={`综合得分：${evaluationDisplay.overall_score}`} sx={{ justifyContent: 'flex-start', bgcolor: 'rgba(125,211,252,0.12)', color: '#7dd3fc' }} />
                  {evaluationDisplay.content_analysis && (
                    <Box
                      sx={{
                        p: 1.4,
                        borderRadius: 2,
                        bgcolor: 'rgba(255,255,255,0.04)',
                        border: '1px solid rgba(125,211,252,0.12)',
                      }}
                    >
                      <Typography variant="subtitle2" sx={{ color: '#f8fafc', fontWeight: 700, mb: 0.8 }}>
                        内容分析
                      </Typography>
                      <Typography variant="body2" sx={{ color: 'rgba(226,232,240,0.84)', lineHeight: 1.75 }}>
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
                      bgcolor: 'rgba(255,255,255,0.04)',
                      border: '1px solid rgba(148,163,184,0.12)',
                    }}
                  >
                    
                    <Typography
                      variant="body2"
                      sx={{
                        mt: 0.9,
                        color: 'rgba(226,232,240,0.84)',
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
                bgcolor: 'rgba(15,23,42,0.72)',
                backgroundImage: 'linear-gradient(180deg, rgba(245,158,11,0.08) 0%, rgba(15,23,42,0.78) 100%)',
              }}
            >
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.35 }}>
                <LightbulbRoundedIcon sx={{ color: '#fbbf24', fontSize: 20 }} />
                <Typography variant="subtitle1" sx={{ color: '#f8fafc', fontWeight: 700 }}>
                作答提示
                </Typography>
              </Stack>
              <Typography variant="body2" sx={{ color: 'rgba(226,232,240,0.72)', mb: 1.45, lineHeight: 1.7 }}>
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
                        bgcolor: 'rgba(255,255,255,0.04)',
                        border: '1px solid rgba(245,158,11,0.14)',
                      }}
                    >
                      <Typography
                        variant="body2"
                        sx={{
                          color: '#edf4ff',
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
                        bgcolor: 'rgba(255,255,255,0.04)',
                        border: '1px solid rgba(245,158,11,0.14)',
                      }}
                    >
                      <Typography variant="body2" sx={{ color: '#edf4ff', fontSize: '0.96rem', lineHeight: 1.75 }}>
                        先给出你的判断，再解释原因，最后补充影响或复盘结论。
                      </Typography>
                    </Box>
                    <Box
                      sx={{
                        p: 1.35,
                        borderRadius: 2,
                        bgcolor: 'rgba(255,255,255,0.04)',
                        border: '1px solid rgba(245,158,11,0.14)',
                      }}
                    >
                      <Typography variant="body2" sx={{ color: '#edf4ff', fontSize: '0.96rem', lineHeight: 1.75 }}>
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
                bgcolor: 'rgba(15,23,42,0.72)',
                backgroundImage: 'linear-gradient(180deg, rgba(52,211,153,0.08) 0%, rgba(15,23,42,0.78) 100%)',
              }}
            >
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.35 }}>
                <MenuBookRoundedIcon sx={{ color: '#6ee7b7', fontSize: 20 }} />
                <Typography variant="subtitle1" sx={{ color: '#f8fafc', fontWeight: 700 }}>
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
                        bgcolor: 'rgba(255,255,255,0.04)',
                        border: '1px solid rgba(52,211,153,0.14)',
                      }}
                    >
                      <Typography variant="body2" sx={{ color: '#f8fafc', fontSize: '0.98rem', fontWeight: 700 }}>
                        {resource.title}
                      </Typography>
                      <Typography variant="body2" sx={{ mt: 0.65, color: 'rgba(226,232,240,0.82)', fontSize: '0.93rem', lineHeight: 1.7 }}>
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
                    bgcolor: 'rgba(255,255,255,0.04)',
                    border: '1px solid rgba(52,211,153,0.14)',
                  }}
                >
                  <Typography variant="body2" sx={{ color: '#edf4ff', fontSize: '0.96rem', lineHeight: 1.75 }}>
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
