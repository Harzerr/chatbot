import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded';
import DownloadRoundedIcon from '@mui/icons-material/DownloadRounded';
import FactCheckRoundedIcon from '@mui/icons-material/FactCheckRounded';
import RefreshRoundedIcon from '@mui/icons-material/RefreshRounded';
import chatService from '../services/chatService';

const pendingStatuses = new Set(['queued', 'processing']);
const safeFileNamePart = (value = '') => String(value).replace(/[\\/:*?"<>|]/g, '-').trim();
const reportFileName = (report) => `${safeFileNamePart(report?.interview_role || '模拟面试')}-${safeFileNamePart(report?.target_company || '通用岗位')}-面试评估报告.pdf`;
const verdictLabel = { correct: '证据正确', incorrect: '证据不对', partial: '部分相关' };

const InterviewEvaluation = () => {
  const { chatId } = useParams();
  const navigate = useNavigate();
  const reportCacheKey = `interview-evaluation-report:${chatId}`;
  const readCachedReport = () => {
    try {
      const cached = sessionStorage.getItem(reportCacheKey);
      return cached ? JSON.parse(cached) : { interview_questions: [] };
    } catch (cacheError) {
      return { interview_questions: [] };
    }
  };
  // Persisted evaluations are displayed immediately; the API refresh is
  // background-only and never blocks navigation or the transcript view.
  const [report, setReport] = useState(readCachedReport);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [feedbackDrafts, setFeedbackDrafts] = useState({});
  const [submittingPointId, setSubmittingPointId] = useState('');
  const [exporting, setExporting] = useState(false);
  const [retryingPointId, setRetryingPointId] = useState('');

  const loadReport = async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const request = chatService.getInterviewReport(chatId, { partial: true });
      const response = await Promise.race([
        request,
        new Promise((_, reject) => window.setTimeout(() => reject(new Error('评估报告加载超时，请点击刷新或重新评估。')), 15000)),
      ]);
      setReport(response);
      try { sessionStorage.setItem(reportCacheKey, JSON.stringify(response)); } catch (cacheError) { /* best effort */ }
      setError('');
      setFeedbackDrafts((previous) => {
        const next = { ...previous };
        (response.interview_questions || []).forEach((question) => {
          (question.evidence_feedback || []).forEach((item) => {
            const key = `${question.point_id}:${item.evidence_id}`;
            if (!next[key]) next[key] = item;
          });
        });
        return next;
      });
      return response;
    } catch (requestError) {
      console.error('Failed to load interview evaluation:', requestError);
      setError(requestError.response?.data?.detail || '评估报告加载失败，请稍后重试。');
      return null;
    } finally {
      if (!silent) setLoading(false);
    }
  };

  // The full report may generate reference answers synchronously. Load the
  // lightweight report first so the page becomes usable immediately; users
  // can refresh or re-evaluate individual questions afterwards.
  useEffect(() => {
    setReport(readCachedReport());
    loadReport(true);
  }, [chatId]);

  const hasPendingEvaluation = useMemo(
    () => (report?.interview_questions || []).some((item) => pendingStatuses.has(item.evaluation_status)),
    [report],
  );

  useEffect(() => {
    if (!hasPendingEvaluation) return undefined;
    const timer = window.setInterval(() => loadReport(true), 1800);
    return () => window.clearInterval(timer);
  }, [hasPendingEvaluation, chatId]);

  const updateFeedback = (pointId, evidenceId, values) => {
    const key = `${pointId}:${evidenceId}`;
    setFeedbackDrafts((previous) => ({
      ...previous,
      [key]: { ...(previous[key] || { evidence_id: evidenceId }), ...values },
    }));
  };

  const submitFeedback = async (question) => {
    const feedback = (question.evaluation?.knowledge_evidence_items || [])
      .map((item) => feedbackDrafts[`${question.point_id}:${item.evidence_id}`])
      .filter((item) => item?.verdict)
      .map((item) => ({ evidence_id: item.evidence_id, verdict: item.verdict, correction: item.correction || '' }));
    if (!question.point_id || feedback.length === 0) return;
    setSubmittingPointId(question.point_id);
    try {
      await chatService.submitEvidenceFeedback(chatId, question.point_id, feedback);
      await loadReport(true);
    } catch (requestError) {
      console.error('Failed to submit evidence feedback:', requestError);
      setError(requestError.response?.data?.detail || '证据核对提交失败，请稍后重试。');
    } finally {
      setSubmittingPointId('');
    }
  };

  const retryEvaluation = async (question) => {
    if (!question.point_id || retryingPointId) return;
    setRetryingPointId(question.point_id);
    try {
      await chatService.retryEvaluation(chatId, question.point_id);
      await loadReport(true);
    } catch (requestError) {
      setError(requestError.response?.data?.detail || '重新评估提交失败，请稍后重试。');
    } finally {
      setRetryingPointId('');
    }
  };

  const exportReport = async () => {
    if (hasPendingEvaluation || exporting) return;
    setExporting(true);
    try {
      const blob = await chatService.downloadInterviewReportPdf(chatId);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = reportFileName(report);
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (requestError) {
      console.error('Failed to export interview report:', requestError);
      setError(requestError.response?.data?.detail || '导出评估报告失败，请稍后重试。');
    } finally {
      setExporting(false);
    }
  };

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: '#f4f7fb', py: { xs: 2, md: 4 } }}>
      <Box sx={{ maxWidth: 1120, mx: 'auto', px: { xs: 2, md: 3 } }}>
        <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ xs: 'stretch', md: 'center' }} spacing={2} sx={{ mb: 2.5 }}>
          <Box>
            <Button startIcon={<ArrowBackRoundedIcon />} onClick={() => navigate('/chat')} sx={{ mb: 0.8, px: 0 }}>返回面试</Button>
            <Typography variant="h4">面试评估</Typography>
            <Typography color="text.secondary" sx={{ mt: 0.5 }}>{report.interview_role || '模拟面试'}{report.target_company ? ` · ${report.target_company}` : ''}</Typography>
          </Box>
          <Stack direction="row" spacing={1} justifyContent="flex-end">
            <Button variant="outlined" startIcon={<RefreshRoundedIcon />} onClick={() => loadReport()} disabled={loading}>刷新状态</Button>
            <Button variant="contained" startIcon={<DownloadRoundedIcon />} onClick={exportReport} disabled={hasPendingEvaluation || exporting}>
              {hasPendingEvaluation ? '评估完成后导出' : exporting ? '导出中…' : '导出评估报告'}
            </Button>
          </Stack>
        </Stack>

        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        {loading && <Alert severity="info" sx={{ mb: 2 }}>正在加载问答与评估状态，页面已可使用；评估不会阻塞当前页面。</Alert>}
        {hasPendingEvaluation && <Alert severity="info" sx={{ mb: 2 }}>部分题目正在评估中，页面会自动刷新；完成后即可导出报告。</Alert>}

        <Paper sx={{ p: { xs: 2, md: 3 }, mb: 2.5 }}>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={2.5} justifyContent="space-between">
            <Box sx={{ flex: 1 }}><Typography variant="h6">评估结论</Typography><Typography sx={{ mt: 1, lineHeight: 1.8 }}>{report.summary || '暂未形成总结。'}</Typography><Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>有效作答：{report.total_answers || 0} 题 · 评估版本：{report.assessment_version || 'legacy'}</Typography></Box>
            <Chip color="primary" label={report.overall_score == null ? '待形成综合分' : `综合得分 ${report.overall_score}`} sx={{ alignSelf: 'flex-start', fontSize: '1rem', py: 2.2 }} />
          </Stack>
          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mt: 2 }}>
            {[['技术准确性', report.technical_accuracy], ['知识深度', report.knowledge_depth], ['表达清晰度', report.communication_clarity], ['逻辑结构', report.logical_structure], ['问题解决', report.problem_solving], ['岗位匹配', report.job_match_score]].map(([label, score]) => score != null && <Chip key={label} size="small" label={`${label} ${score}`} variant="outlined" />)}
          </Stack>
          {(report.strengths?.length > 0 || report.improvement_areas?.length > 0 || report.content_analysis) && <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} sx={{ mt: 2 }}>
            {report.strengths?.length > 0 && <Box sx={{ flex: 1 }}><Typography variant="subtitle2" color="success.main">表现较好的地方</Typography>{report.strengths.map((item) => <Typography key={item} variant="body2" sx={{ mt: 0.5, lineHeight: 1.65 }}>· {item}</Typography>)}</Box>}
            {report.improvement_areas?.length > 0 && <Box sx={{ flex: 1 }}><Typography variant="subtitle2" color="warning.dark">建议改进</Typography>{report.improvement_areas.map((item) => <Typography key={item} variant="body2" sx={{ mt: 0.5, lineHeight: 1.65 }}>· {item}</Typography>)}</Box>}
          </Stack>}
          {report.content_analysis && <Box sx={{ mt: 2, p: 1.5, bgcolor: '#f8fafc', borderRadius: 1.5 }}><Typography variant="subtitle2">内容分析</Typography><Typography variant="body2" sx={{ mt: 0.5, lineHeight: 1.75, whiteSpace: 'pre-wrap' }}>{report.content_analysis}</Typography></Box>}
          {report.recommendations?.length > 0 && <Box sx={{ mt: 2 }}><Typography variant="subtitle2">后续建议</Typography><Stack spacing={0.4} sx={{ mt: 0.5 }}>{report.recommendations.map((item) => <Typography key={item} variant="body2" sx={{ lineHeight: 1.65 }}>· {item}</Typography>)}</Stack></Box>}
          {report.recommended_resources?.length > 0 && <Box sx={{ mt: 2 }}><Typography variant="subtitle2">推荐学习资源</Typography><Stack spacing={0.5} sx={{ mt: 0.5 }}>{report.recommended_resources.map((item) => <Typography key={`${item.title}-${item.category}`} variant="body2" sx={{ lineHeight: 1.65 }}>{item.title}：{item.reason}</Typography>)}</Stack></Box>}
        </Paper>

        {report.competency_assessments?.length > 0 && <Paper sx={{ p: { xs: 2, md: 3 }, mb: 2.5 }}><Typography variant="h6">能力覆盖与评估依据</Typography><Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, mb: 1.5 }}>{report.coverage_status}</Typography><Stack spacing={1.2}>{report.competency_assessments.map((item) => <Box key={item.capability} sx={{ p: 1.4, bgcolor: '#f8fafc', borderRadius: 1.5 }}><Stack direction="row" justifyContent="space-between" spacing={1}><Typography fontWeight={700}>{item.capability}</Typography><Chip size="small" label={`${item.score} 分 · ${item.covered_questions} 题 · ${item.confidence}置信度`} /></Stack>{item.evidence?.map((evidence) => <Typography key={evidence} variant="body2" sx={{ mt: 0.5, lineHeight: 1.65 }}>依据：{evidence}</Typography>)}{item.missing_points?.map((point) => <Typography key={point} variant="body2" color="text.secondary" sx={{ mt: 0.4 }}>待补：{point}</Typography>)}</Box>)}</Stack></Paper>}

        <Paper sx={{ p: { xs: 2, md: 3 } }}>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}><FactCheckRoundedIcon color="primary" /><Typography variant="h6">逐题评估与证据核对</Typography></Stack>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>召回证据只作为评估依据，不等于候选人已经证明的经历。请核对证据是否真的支持本题判断；标记错误并补充说明后，系统会强制重新评估。</Typography>
          <Stack spacing={2}>
            {(report.interview_questions || []).map((question, index) => {
              const evaluation = question.evaluation || {};
              const evidenceItems = question.evaluation?.knowledge_evidence_items || [];
              const rubricScores = evaluation.rubric_scores || [];
              const answerEvidence = Array.from(new Set([
                ...(evaluation.resume_evidence || []),
                ...(evaluation.capability_assessments || []).flatMap((item) => item.evidence || []),
                ...(evaluation.jd_requirement_matches || []).flatMap((item) => item.evidence || []),
                ...rubricScores.flatMap((item) => item.evidence || []),
              ].filter(Boolean)));
              const plainKnowledgeEvidence = evaluation.knowledge_evidence || [];
              const isPending = pendingStatuses.has(question.evaluation_status);
              return (
                <Box key={question.point_id || index} sx={{ p: 2, border: '1px solid rgba(148,163,184,0.24)', borderRadius: 2, bgcolor: '#fff' }}>
                  <Typography variant="overline" color="primary">第 {index + 1} 题</Typography>
                  <Typography sx={{ fontWeight: 700, lineHeight: 1.7 }}>{question.question || '未记录问题'}</Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 0.7, whiteSpace: 'pre-wrap', lineHeight: 1.7 }}>{question.candidate_answer || '未记录回答'}</Typography>
                  <Divider sx={{ my: 1.5 }} />
                  {isPending ? <Stack direction="row" spacing={1} alignItems="center"><CircularProgress size={16} /><Typography color="text.secondary">本题正在评估…</Typography><Button size="small" startIcon={<RefreshRoundedIcon />} onClick={() => retryEvaluation(question)} disabled={retryingPointId === question.point_id}>重新入队</Button></Stack> : question.evaluation_status === 'failed' ? <><Alert severity="error">评估失败：{question.evaluation_error || '评估服务暂时不可用。'}</Alert><Button sx={{ mt: 1 }} size="small" variant="outlined" startIcon={<RefreshRoundedIcon />} onClick={() => retryEvaluation(question)} disabled={retryingPointId === question.point_id}>重新评估</Button></> : (
                    <>
                      <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mb: 1 }}><Chip size="small" label={`综合 ${question.evaluation?.overall_score ?? '暂无'} 分`} color="primary" /><Chip size="small" label={question.evaluation?.verdict || '已完成'} variant="outlined" />{question.evaluation?.evaluation_mode === 'fallback' && <Chip size="small" label="规则降级" color="warning" variant="outlined" />}</Stack>
                      <Typography variant="body2" sx={{ lineHeight: 1.75 }}>{evaluation.summary || '暂无评估摘要。'}</Typography>
                      {evaluation.correctness_summary && <Box sx={{ mt: 1, p: 1.2, bgcolor: '#f8fafc', borderRadius: 1.5 }}><Typography variant="subtitle2">正确性判断</Typography><Typography variant="body2" sx={{ mt: 0.4, lineHeight: 1.7 }}>{evaluation.correctness_summary}</Typography></Box>}
                      {rubricScores.length > 0 && <Box sx={{ mt: 1.5 }}><Typography variant="subtitle2">评分 Rubric 与判定理由</Typography><Stack spacing={0.8} sx={{ mt: 0.7 }}>{rubricScores.map((item) => <Box key={item.dimension} sx={{ p: 1, border: '1px solid rgba(148,163,184,0.18)', borderRadius: 1 }}><Stack direction="row" justifyContent="space-between"><Typography variant="body2" fontWeight={700}>{item.label || item.dimension}</Typography><Chip size="small" label={`${item.score}/4`} /></Stack>{item.rationale && <Typography variant="body2" sx={{ mt: 0.4, lineHeight: 1.6 }}>{item.rationale}</Typography>}{item.evidence?.length > 0 && <Typography variant="caption" sx={{ display: 'block', mt: 0.4, color: '#475569', lineHeight: 1.55 }}>本维度引用：{item.evidence.join('；')}</Typography>}{item.missing_points?.map((point) => <Typography key={point} variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.3 }}>待补充：{point}</Typography>)}</Box>)}</Stack></Box>}
                      {answerEvidence.length > 0 && <Box sx={{ mt: 1.5, p: 1.2, bgcolor: '#fffdf5', border: '1px solid rgba(245,158,11,0.25)', borderRadius: 1.5 }}><Typography variant="subtitle2">评估引用的回答/简历依据</Typography>{answerEvidence.map((item) => <Typography key={item} variant="body2" sx={{ mt: 0.4, lineHeight: 1.65 }}>· {item}</Typography>)}</Box>}
                      {plainKnowledgeEvidence.length > 0 && evidenceItems.length === 0 && <Box sx={{ mt: 1.5 }}><Typography variant="subtitle2">RAG 召回证据原文</Typography>{plainKnowledgeEvidence.map((item) => <Typography key={item} variant="body2" sx={{ mt: 0.5, p: 1, bgcolor: '#f8fafc', whiteSpace: 'pre-wrap', lineHeight: 1.65 }}>{item}</Typography>)}</Box>}
                      {evidenceItems.length === 0 && evaluation.question_type !== '代码题' && <Alert severity="info" sx={{ mt: 1.5 }}>本题没有形成可核对的职业事实证据，当前评分仅依据候选人回答、简历和规则；不会把未召回的内容当作 RAG 证据。</Alert>}
                      {evaluation.evaluation_mode === 'fallback' && evaluation.evaluation_basis?.length > 0 && <Box sx={{ mt: 1.5 }}><Typography variant="subtitle2">规则/降级评估依据</Typography>{Array.from(new Set(evaluation.evaluation_basis)).map((item) => <Typography key={item} variant="body2" sx={{ mt: 0.4, lineHeight: 1.65 }}>· {item}</Typography>)}</Box>}
                      {evaluation.expected_key_points?.length > 0 && <Box sx={{ mt: 1.5 }}><Typography variant="subtitle2">应覆盖的关键点</Typography>{evaluation.expected_key_points.map((item) => <Typography key={item} variant="body2" sx={{ mt: 0.4 }}>· {item}</Typography>)}</Box>}
                      {evaluation.correction_suggestion && <Typography variant="body2" color="warning.dark" sx={{ mt: 1 }}>改进建议：{evaluation.correction_suggestion}</Typography>}
                      {question.reference_answer && <Box sx={{ mt: 1.5, p: 1.2, bgcolor: '#f8fafc', borderRadius: 1.5 }}><Typography variant="subtitle2">参考答案</Typography><Typography variant="body2" sx={{ mt: 0.4, whiteSpace: 'pre-wrap', lineHeight: 1.7 }}>{question.reference_answer}</Typography></Box>}
                      {evidenceItems.length > 0 && <Stack spacing={1.2} sx={{ mt: 1.5 }}><Typography variant="subtitle2">RAG 召回的职业事实证据（逐条核对）</Typography><Typography variant="caption" color="text.secondary">每条证据都有唯一 ID；选择“证据正确 / 证据不对 / 部分相关”后提交，系统会把核验结果连同本题重新送入评估。</Typography>{evidenceItems.map((evidence) => { const key = `${question.point_id}:${evidence.evidence_id}`; const draft = feedbackDrafts[key] || {}; return <Box key={evidence.evidence_id} sx={{ p: 1.4, bgcolor: '#f8fafc', border: '1px solid rgba(125,211,252,0.35)', borderRadius: 1.5 }}><Typography variant="caption" color="text.secondary">{evidence.document_title || '技术文档'} · {evidence.section || '未标注章节'} · {evidence.evidence_id} · 来源：{evidence.retrieval_method || 'unknown'}</Typography><Typography variant="body2" sx={{ mt: 0.6, whiteSpace: 'pre-wrap', lineHeight: 1.7 }}>{evidence.quote || '暂无证据原文。'}</Typography><Stack direction="row" spacing={1} sx={{ mt: 1 }}>{Object.entries(verdictLabel).map(([verdict, label]) => <Button key={verdict} size="small" variant={draft.verdict === verdict ? 'contained' : 'outlined'} color={verdict === 'incorrect' ? 'error' : verdict === 'partial' ? 'warning' : 'success'} onClick={() => updateFeedback(question.point_id, evidence.evidence_id, { verdict })}>{label}</Button>)}</Stack>{(draft.verdict === 'incorrect' || draft.verdict === 'partial') && <TextField fullWidth size="small" multiline minRows={2} label="告诉模型哪里不对（可补充正确证据或边界）" value={draft.correction || ''} onChange={(event) => updateFeedback(question.point_id, evidence.evidence_id, { correction: event.target.value })} sx={{ mt: 1 }} />}</Box>; })}<Button variant="contained" onClick={() => submitFeedback(question)} disabled={submittingPointId === question.point_id} sx={{ alignSelf: 'flex-start' }}>{submittingPointId === question.point_id ? '已提交，重新评估中…' : '提交核对并重新评估本题'}</Button></Stack>}
                      <Button sx={{ mt: 1.5 }} size="small" variant="outlined" startIcon={<RefreshRoundedIcon />} onClick={() => retryEvaluation(question)} disabled={retryingPointId === question.point_id}>重新评估本题</Button>
                    </>
                  )}
                </Box>
              );
            })}
          </Stack>
        </Paper>
      </Box>
    </Box>
  );
};

export default InterviewEvaluation;
