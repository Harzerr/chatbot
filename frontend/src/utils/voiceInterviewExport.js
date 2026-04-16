const sanitizeFileNamePart = (value = '') => String(value)
  .replace(/[\\/:*?"<>|]/g, '-')
  .trim();

const formatTimestamp = (value) => {
  if (!value) {
    return '';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toLocaleString('zh-CN', { hour12: false });
};

const buildFileName = (interviewContext = {}) => {
  const role = sanitizeFileNamePart(interviewContext.interviewRole || '通用软件工程师');
  const interviewType = sanitizeFileNamePart(interviewContext.interviewType || '语音面试');
  const timestamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\..+$/, '');
  return `${role}-${interviewType}-语音面试记录与评估-${timestamp}.md`;
};

const renderTranscript = (transcript = []) => {
  if (!transcript.length) {
    return '暂无可导出的语音对话记录。';
  }

  return transcript.map((turn, index) => {
    const role = turn.role === 'candidate' ? '候选人' : '面试官';
    const time = formatTimestamp(turn.timestamp);
    const prefix = time ? `${index + 1}. ${role} [${time}]` : `${index + 1}. ${role}`;
    return `${prefix}\n${turn.text}`;
  }).join('\n\n');
};

const renderList = (items = []) => {
  if (!items.length) {
    return '- 暂无';
  }
  return items.map((item) => `- ${item}`).join('\n');
};

export const downloadVoiceInterviewBundle = ({ interviewContext = {}, transcript = [], report = null }) => {
  const content = [
    '# 语音面试记录与评估',
    '',
    '## 面试信息',
    `- 岗位：${interviewContext.interviewRole || '未设置'}`,
    `- 级别：${interviewContext.interviewLevel || '未设置'}`,
    `- 轮次：${interviewContext.interviewType || '未设置'}`,
    `- 目标公司：${interviewContext.targetCompany || '未设置'}`,
    '',
    '## 面试评价',
    report ? [
      `- 综合得分：${report.overall_score ?? 0}`,
      `- 技术准确性：${report.technical_accuracy ?? 0}`,
      `- 知识深度：${report.knowledge_depth ?? 0}`,
      `- 表达清晰度：${report.communication_clarity ?? 0}`,
      `- 逻辑结构：${report.logical_structure ?? 0}`,
      `- 问题解决：${report.problem_solving ?? 0}`,
      `- 岗位匹配度：${report.job_match_score ?? 0}`,
      '',
      '### 总结',
      report.summary || '暂无总结',
      '',
      '### 内容分析',
      report.content_analysis || '暂无内容分析',
      '',
      '### 优势亮点',
      renderList(report.strengths),
      '',
      '### 待改进项',
      renderList(report.improvement_areas),
      '',
      '### 面试建议',
      renderList(report.recommendations),
    ].join('\n') : '尚未生成面试评价。',
    '',
    '## 语音对话记录',
    renderTranscript(transcript),
    '',
  ].join('\n');

  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = buildFileName(interviewContext);
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
};

