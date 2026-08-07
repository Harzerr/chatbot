import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Alert,
  AppBar,
  Box,
  Button,
  Chip,
  CircularProgress,
  Container,
  Divider,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Switch,
  Tab,
  Tabs,
  TextField,
  Tooltip,
  Toolbar,
  Typography,
} from '@mui/material';
import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded';
import AutoAwesomeRoundedIcon from '@mui/icons-material/AutoAwesomeRounded';
import FactCheckRoundedIcon from '@mui/icons-material/FactCheckRounded';
import LinkRoundedIcon from '@mui/icons-material/LinkRounded';
import DescriptionRoundedIcon from '@mui/icons-material/DescriptionRounded';
import DownloadRoundedIcon from '@mui/icons-material/DownloadRounded';
import VisibilityRoundedIcon from '@mui/icons-material/VisibilityRounded';
import CodeRoundedIcon from '@mui/icons-material/CodeRounded';
import AddRoundedIcon from '@mui/icons-material/AddRounded';
import ArchiveRoundedIcon from '@mui/icons-material/ArchiveRounded';
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded';
import EditRoundedIcon from '@mui/icons-material/EditRounded';
import RestoreRoundedIcon from '@mui/icons-material/RestoreRounded';
import SaveRoundedIcon from '@mui/icons-material/SaveRounded';
import RecordVoiceOverRoundedIcon from '@mui/icons-material/RecordVoiceOverRounded';
import careerService from '../services/careerService';
import { useAuth } from '../contexts/AuthContext';

const factTypes = ['experience', 'project', 'skill', 'education', 'certificate', 'award', 'language', 'other'];
const factTypeLabels = {
  experience: '实习/工作经历',
  project: '项目经历',
  skill: '专业技能',
  education: '教育背景',
  certificate: '证书',
  award: '竞赛与荣誉',
  language: '语言能力',
  other: '其他',
};
const factTagLabels = {
  education: '教育背景',
  experience: '经历',
  internship: '实习经历',
  project: '项目经历',
  skill: '专业技能',
  certificate: '证书',
  award: '竞赛与荣誉',
  language: '语言能力',
  master: '硕士',
  bachelor: '本科',
  phd: '博士',
  research: '科研经历',
  work: '工作经历',
};
const localizeFactTag = (tag) => factTagLabels[String(tag || '').trim().toLowerCase()] || tag;

const downloadBlob = (blob, name) => {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
};

const splitLines = (value) => String(value || '').split('\n').map((item) => item.trim()).filter(Boolean);
const joinLines = (value) => (Array.isArray(value) ? value : []).join('\n');

const factToEditor = (fact) => ({
  id: fact?.id,
  fact_type: fact?.fact_type || 'project',
  title: fact?.title || '',
  summary: fact?.content?.summary || '',
  highlights: joinLines(fact?.content?.highlights),
  tags: (fact?.tags || []).map(localizeFactTag).join(', '),
  evidence: fact?.evidence || '',
  is_verified: fact?.is_verified ?? true,
});

const jobToEditor = (job) => ({
  id: job?.id,
  title: job?.title || '',
  company: job?.company || '',
  raw_content: job?.raw_content || '',
  summary: job?.normalized?.summary || '',
  required_skills: joinLines(job?.normalized?.required_skills),
  preferred_skills: joinLines(job?.normalized?.preferred_skills),
  responsibilities: joinLines(job?.normalized?.responsibilities),
  education_requirements: joinLines(job?.normalized?.education_requirements),
  language_requirements: joinLines(job?.normalized?.language_requirements),
  keywords: joinLines(job?.normalized?.keywords),
});

const jobRequirements = (job) => {
  const normalized = job?.normalized || {};
  return [
    ['核心要求', normalized.required_skills || []],
    ['工作职责', normalized.responsibilities || []],
    ['加分项', normalized.preferred_skills || []],
    ['学历要求', normalized.education_requirements || []],
    ['语言要求', normalized.language_requirements || []],
  ].flatMap(([group, values]) => values.map((text) => ({ group, text: String(text) })));
};

const requirementEvidence = (requirement, facts) => {
  const target = requirement.toLowerCase();
  return facts.filter((fact) => {
    const content = fact.content || {};
    const text = [fact.title, content.summary, ...(content.highlights || []), ...(fact.tags || [])].join(' ').toLowerCase();
    if (text.includes(target) || target.includes(String(fact.title || '').toLowerCase())) return true;
    const englishTerms = target.match(/[a-z0-9+#.]{3,}/g) || [];
    return englishTerms.some((term) => text.includes(term));
  });
};

const JsonPanel = ({ value }) => (
  <Box
    component="pre"
    sx={{
      m: 0,
      p: 2,
      overflow: 'auto',
      maxHeight: 360,
      whiteSpace: 'pre-wrap',
      wordBreak: 'break-word',
      fontSize: 12,
      lineHeight: 1.65,
      color: '#cbd5e1',
      bgcolor: 'rgba(2, 6, 23, 0.48)',
      border: '1px solid rgba(125, 211, 252, 0.10)',
      borderRadius: 1,
    }}
  >
    {JSON.stringify(value, null, 2)}
  </Box>
);

const CareerStudio = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { currentUser } = useAuth();
  const [tab, setTab] = useState(() => Math.max(0, Math.min(2, Number(searchParams.get('tab')) || 0)));
  const [facts, setFacts] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [resumes, setResumes] = useState([]);
  const [draftFacts, setDraftFacts] = useState([]);
  const [selectedJobId, setSelectedJobId] = useState('');
  const [previewResumeId, setPreviewResumeId] = useState('');
  const [jobUrl, setJobUrl] = useState('');
  const [jobText, setJobText] = useState('');
  const [factEditor, setFactEditor] = useState(null);
  const [jobEditor, setJobEditor] = useState(null);
  const [showArchived, setShowArchived] = useState(false);
  const [selectedFactIds, setSelectedFactIds] = useState([]);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [workingAction, setWorkingAction] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [factExtractionWarnings, setFactExtractionWarnings] = useState([]);
  const [exportingPdf, setExportingPdf] = useState(false);
  const [previewPdfUrl, setPreviewPdfUrl] = useState('');
  const [previewPdfLoading, setPreviewPdfLoading] = useState(false);
  const [previewPdfVersion, setPreviewPdfVersion] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [factData, jobData, resumeData] = await Promise.all([
        careerService.listFacts(),
        careerService.listJobs(),
        careerService.listResumes(),
      ]);
      setFacts(factData);
      setJobs(jobData);
      setResumes(resumeData);
      setSelectedJobId((current) => current || (jobData[0] ? String(jobData[0].id) : ''));
      setSelectedFactIds((current) => current.length ? current : factData.filter((fact) => fact.is_verified).map((fact) => fact.id));
    } catch (err) {
      setError(err.response?.data?.detail || '加载求职工作台失败。');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const requestedTab = Number(searchParams.get('tab'));
    if (Number.isInteger(requestedTab) && requestedTab >= 0 && requestedTab <= 2) setTab(requestedTab);
  }, [searchParams]);

  useEffect(() => {
    let disposed = false;
    let objectUrl = '';
    if (!previewResumeId) {
      setPreviewPdfUrl('');
      return undefined;
    }
    setPreviewPdfLoading(true);
    setPreviewPdfUrl('');
    careerService.downloadResumePdf(previewResumeId)
      .then((response) => {
        objectUrl = URL.createObjectURL(response.data);
        if (disposed) {
          URL.revokeObjectURL(objectUrl);
          return;
        }
        setPreviewPdfUrl(objectUrl);
      })
      .catch((err) => {
        if (!disposed) setError(err.response?.data?.detail || '加载投递版 PDF 预览失败，请重试。');
      })
      .finally(() => {
        if (!disposed) setPreviewPdfLoading(false);
      });
    return () => {
      disposed = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [previewResumeId, previewPdfVersion]);

  const run = async (action, successMessage, actionKey = '') => {
    setWorking(true);
    setWorkingAction(actionKey);
    setError('');
    setNotice('');
    try {
      await action();
      setNotice(successMessage);
    } catch (err) {
      setError(err.response?.data?.detail || err.message || '操作失败，请稍后重试。');
    } finally {
      setWorking(false);
      setWorkingAction('');
    }
  };

  const extractFacts = () => run(async () => {
    if (!currentUser?.has_resume) {
      throw new Error('请先到个人档案上传简历。');
    }
    setFactExtractionWarnings([]);
    const response = await careerService.extractFacts();
    const extractedFacts = response.facts || [];
    setFactExtractionWarnings(response.warnings || []);
    if (!extractedFacts.length) {
      throw new Error(response.message || 'AI 未从简历中提取到有效事实，请检查简历文本后重试。');
    }
    setDraftFacts(extractedFacts);
  }, '已从现有简历提取待确认事实。确认后才会进入事实库。');

const saveDraftFact = (fact) => run(async () => {
    const saved = await careerService.createFact({ ...fact, is_verified: true });
    setFacts((items) => [saved, ...items]);
    setDraftFacts((items) => items.filter((item) => item !== fact));
  }, '事实已确认并保存。');

  const saveFact = () => run(async () => {
    const isDraftFact = factEditor?.draftIndex !== undefined;
    const payload = {
      fact_type: factEditor.fact_type,
      title: factEditor.title.trim(),
      content: { summary: factEditor.summary.trim(), highlights: splitLines(factEditor.highlights) },
      tags: factEditor.tags.split(',').map((tag) => tag.trim()).filter(Boolean),
      evidence: factEditor.evidence.trim() || undefined,
      is_verified: isDraftFact ? false : factEditor.is_verified,
    };
    if (isDraftFact) {
      setDraftFacts((items) => items.map((item, index) => index === factEditor.draftIndex ? payload : item));
      setFactEditor(null);
      return;
    }
    const saved = factEditor.id
      ? await careerService.updateFact(factEditor.id, payload)
      : await careerService.createFact(payload);
    setFacts((items) => factEditor.id ? items.map((fact) => fact.id === saved.id ? saved : fact) : [saved, ...items]);
    if (saved.is_verified) setSelectedFactIds((ids) => ids.includes(saved.id) ? ids : [...ids, saved.id]);
    setFactEditor(null);
  }, factEditor?.draftIndex !== undefined ? '待确认事实已更新。' : factEditor?.id ? '事实已更新。' : '事实已保存。');

  const archiveFact = (fact) => run(async () => {
    const saved = await careerService.archiveFact(fact.id);
    setFacts((items) => items.map((item) => item.id === saved.id ? saved : item));
    setSelectedFactIds((ids) => ids.filter((id) => id !== fact.id));
  }, '事实已移至归档，不会再用于生成。');

  const restoreFact = (fact) => run(async () => {
    const saved = await careerService.updateFact(fact.id, { is_archived: false });
    setFacts((items) => items.map((item) => item.id === saved.id ? saved : item));
  }, '事实已恢复到事实库。');

  const deleteFact = (fact) => {
    if (!window.confirm(`永久删除“${fact.title}”？该事实不会再出现在事实库中，且无法恢复。`)) return;
    return run(async () => {
      await careerService.deleteFact(fact.id);
      setFacts((items) => items.filter((item) => item.id !== fact.id));
      setSelectedFactIds((ids) => ids.filter((id) => id !== fact.id));
    }, '事实已永久删除。');
  };

  const saveJob = () => run(async () => {
    const current = jobs.find((job) => job.id === jobEditor.id);
    const normalized = {
      ...(current?.normalized || {}),
      title: jobEditor.title.trim(),
      company: jobEditor.company.trim(),
      summary: jobEditor.summary.trim(),
      required_skills: splitLines(jobEditor.required_skills),
      preferred_skills: splitLines(jobEditor.preferred_skills),
      responsibilities: splitLines(jobEditor.responsibilities),
      education_requirements: splitLines(jobEditor.education_requirements),
      language_requirements: splitLines(jobEditor.language_requirements),
      keywords: splitLines(jobEditor.keywords),
    };
    const saved = await careerService.updateJob(jobEditor.id, {
      title: jobEditor.title.trim(), company: jobEditor.company.trim(), raw_content: jobEditor.raw_content.trim(), normalized,
    });
    setJobs((items) => items.map((job) => job.id === saved.id ? saved : job));
    setJobEditor(null);
  }, '职位要求已更新，对岗预检将立即使用新内容。');

  const deleteJob = (job) => {
    if (!window.confirm(`删除“${job.title || '该职位'}”及其关联定制简历？此操作不可恢复。`)) return;
    return run(async () => {
    await careerService.deleteJob(job.id);
    setJobs((items) => items.filter((item) => item.id !== job.id));
    setResumes((items) => items.filter((item) => item.job_id !== job.id));
    setSelectedJobId((id) => String(id) === String(job.id) ? '' : id);
    }, '职位及其定制简历已删除。');
  };

  const deleteResume = (resume) => {
    if (!window.confirm(`删除“${resume.title}”？此操作不可恢复。`)) return;
    return run(async () => {
    await careerService.deleteResume(resume.id);
    setResumes((items) => items.filter((item) => item.id !== resume.id));
    setPreviewResumeId((id) => String(id) === String(resume.id) ? '' : id);
    }, '定制简历已删除。');
  };

  const importJob = () => run(async () => {
    const saved = await careerService.importJob({
      source_url: jobUrl.trim() || undefined,
      raw_content: jobText.trim() || undefined,
    });
    setJobs((items) => [saved, ...items]);
    setSelectedJobId(String(saved.id));
    setJobUrl('');
    setJobText('');
  }, '职位已结构化保存。请检查 JSON 后生成定制简历。');

  const refreshJob = (jobId) => run(async () => {
    const refreshed = await careerService.refreshJob(jobId);
    setJobs((items) => items.map((job) => (job.id === refreshed.id ? refreshed : job)));
    setSelectedJobId(String(refreshed.id));
  }, '已重新抓取并解析职位正文。');

  const generateResume = () => {
    if (!currentUser?.full_name?.trim()) {
      setError('请先在个人档案填写真实姓名。投递版简历不会再使用账号用户名。');
      return;
    }
    return run(async () => {
    const saved = await careerService.generateResume({ job_id: Number(selectedJobId), fact_ids: selectedFactIds });
    setResumes((items) => [saved, ...items]);
    setPreviewResumeId(String(saved.id));
    setTab(2);
    }, '已生成一份仅引用已确认事实的定制简历。', 'generate');
  };

  const exportPdf = async () => {
    if (!previewResume) return;
    setExportingPdf(true);
    setError('');
    try {
      const response = await careerService.downloadResumePdf(previewResume.id);
      downloadBlob(response.data, `${previewResume.title || 'tailored-resume'}.pdf`);
      setNotice('已下载由 XeLaTeX 母版生成的可搜索 PDF。');
    } catch (err) {
      setError(err.message || '导出 PDF 失败，请重试。');
    } finally {
      setExportingPdf(false);
    }
  };

  const exportTex = async () => {
    if (!previewResume) return;
    setWorking(true);
    setError('');
    try {
      const response = await careerService.downloadResumeTex(previewResume.id);
      downloadBlob(response.data, `${previewResume.title || 'tailored-resume'}-tex-source.zip`);
      setNotice('已下载母版 TeX 源码包。');
    } catch (err) {
      setError(err.response?.data?.detail || '导出 TeX 源码失败，请重试。');
    } finally {
      setWorking(false);
    }
  };

  if (loading) {
    return <Box sx={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}><CircularProgress /></Box>;
  }

  const selectedJob = jobs.find((job) => String(job.id) === String(selectedJobId));
  const previewResume = resumes.find((resume) => String(resume.id) === String(previewResumeId));
  const resumeDisplayTitle = (resume) => {
    const job = jobs.find((item) => String(item.id) === String(resume.job_id));
    return job?.company && job?.title ? `${job.company} - ${job.title}` : job?.title || resume.title;
  };
  const activeFacts = facts.filter((fact) => !fact.is_archived);
  const archivedFacts = facts.filter((fact) => fact.is_archived);
  const verifiedFacts = activeFacts.filter((fact) => fact.is_verified);
  const precheck = jobRequirements(selectedJob).map((requirement) => ({
    ...requirement,
    evidence: requirementEvidence(requirement.text, verifiedFacts),
  }));
  const matchedPrecheckCount = precheck.filter((item) => item.evidence.length > 0).length;

  return (
    <Box sx={{ minHeight: '100vh' }}>
      <AppBar position="sticky">
        <Toolbar sx={{ gap: 1.5 }}>
          <Button color="inherit" startIcon={<ArrowBackRoundedIcon />} onClick={() => navigate('/profile')}>个人档案</Button>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>求职工作台</Typography>
          <Chip label={`${facts.filter((fact) => fact.is_verified).length} 条已确认事实`} color="primary" variant="outlined" />
        </Toolbar>
      </AppBar>

      <Container maxWidth="xl" sx={{ py: 3 }}>
        <Stack spacing={2.5}>
          {(error || notice) && <Alert severity={error ? 'error' : 'success'}>{error || notice}</Alert>}
          <Paper elevation={0} sx={{ p: 2, borderRadius: 2 }}>
            <Tabs value={tab} onChange={(_, value) => setTab(value)} variant="scrollable" allowScrollButtonsMobile>
              <Tab icon={<FactCheckRoundedIcon />} iconPosition="start" label="职业事实库" />
              <Tab icon={<LinkRoundedIcon />} iconPosition="start" label="职位库" />
              <Tab icon={<DescriptionRoundedIcon />} iconPosition="start" label="定制简历" />
            </Tabs>
          </Paper>

          {tab === 0 && (
            <Stack spacing={2.5}>
              <Paper elevation={0} sx={{ p: 3, borderRadius: 2 }}>
                <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} justifyContent="space-between" alignItems={{ md: 'center' }}>
                  <Box>
                    <Typography variant="h5">职业事实库</Typography>
                    <Typography color="text.secondary" sx={{ mt: 0.5 }}>保存完整、可核查的职业事实。定制简历只会引用已确认且与职位有关的内容。</Typography>
                  </Box>
                  <Button variant="contained" startIcon={<AutoAwesomeRoundedIcon />} onClick={extractFacts} disabled={working || !currentUser?.has_resume}>{working ? 'AI 正在提取，请稍候…' : '从已上传简历提取事实'}</Button>
                </Stack>
              </Paper>

              {factExtractionWarnings.length > 0 && (
                <Alert severity="warning">
                  部分事实未通过结构校验：{factExtractionWarnings.map((item) => item.title || `第 ${item.index + 1} 条`).join('、')}。可先确认已识别内容，再编辑或手动补充。
                </Alert>
              )}

              {draftFacts.length > 0 && (
                <Paper elevation={0} sx={{ p: 3, borderRadius: 2 }}>
                  <Typography variant="h6" sx={{ mb: 1 }}>待确认事实</Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>这些内容尚未写入事实库。逐条确认后才可用于生成简历。</Typography>
                  <Stack spacing={1.5}>
                    {draftFacts.map((fact, index) => (
                      <Paper key={`${fact.title}-${index}`} variant="outlined" sx={{ p: 2, borderRadius: 1.5 }}>
                        <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} justifyContent="space-between">
                          <Box sx={{ minWidth: 0 }}><Chip size="small" label={factTypeLabels[fact.fact_type] || '其他'} /><Typography sx={{ mt: 1, fontWeight: 700 }}>{fact.title}</Typography><Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, whiteSpace: 'pre-wrap' }}>{fact.content?.summary || fact.evidence || '无摘要'}</Typography>{(fact.content?.highlights || []).map((highlight, highlightIndex) => <Typography key={`${fact.title}-highlight-${highlightIndex}`} variant="body2" color="text.secondary" sx={{ mt: 0.35 }}>• {highlight}</Typography>)}</Box>
                          <Stack direction="row" spacing={0.5} alignItems="center"><Button size="small" startIcon={<EditRoundedIcon />} onClick={() => setFactEditor({ ...factToEditor(fact), draftIndex: index, is_verified: false })} disabled={working}>编辑</Button><Button size="small" onClick={() => saveDraftFact(fact)} disabled={working}>确认事实</Button></Stack>
                        </Stack>
                      </Paper>
                    ))}
                  </Stack>
                </Paper>
              )}

              <Paper elevation={0} sx={{ p: 2.5, borderRadius: 2 }}>
                <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ sm: 'center' }} spacing={1.5}>
                  <Box>
                    <Typography variant="h6">已保存事实</Typography>
                    <Typography variant="body2" color="text.secondary">每条事实都可以编辑、暂存归档或恢复；已确认事实才会进入对岗和生成流程。</Typography>
                  </Box>
                  <Stack direction="row" spacing={1}>
                    <FormControlLabel control={<Switch size="small" checked={showArchived} onChange={(event) => setShowArchived(event.target.checked)} />} label="显示归档" />
                    <Button variant="outlined" startIcon={<AddRoundedIcon />} onClick={() => setFactEditor(factToEditor())}>新建事实</Button>
                  </Stack>
                </Stack>
              </Paper>

              <Stack spacing={1.25}>
                {activeFacts.length === 0 && <Alert severity="info">还没有已保存事实。可从简历提取，或点击“新建事实”手动录入。</Alert>}
                {activeFacts.map((fact) => <Paper key={fact.id} elevation={0} sx={{ p: 2, borderRadius: 1.5, border: '1px solid', borderColor: 'divider' }}>
                  <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} justifyContent="space-between">
                    <Box sx={{ minWidth: 0 }}>
                      <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap"><Chip size="small" label={factTypeLabels[fact.fact_type] || '其他'} /><Typography fontWeight={700}>{fact.title}</Typography><Chip size="small" color={fact.is_verified ? 'success' : 'warning'} label={fact.is_verified ? '已确认' : '待确认'} /></Stack>
                      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.85, whiteSpace: 'pre-wrap' }}>{fact.content?.summary || fact.evidence || '无摘要'}</Typography>
                      {!!fact.evidence && <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.75 }}>依据：{fact.evidence}</Typography>}
                    </Box>
                    <Stack direction="row" spacing={0.5} alignItems="center" useFlexGap flexWrap="wrap">
                      {fact.tags.map((tag) => <Chip key={tag} size="small" label={localizeFactTag(tag)} />)}
                      <Button size="small" startIcon={<EditRoundedIcon />} onClick={() => setFactEditor(factToEditor(fact))}>编辑</Button>
                      <Button size="small" color="warning" startIcon={<ArchiveRoundedIcon />} onClick={() => archiveFact(fact)} disabled={working}>归档</Button>
                      <Button size="small" color="error" startIcon={<DeleteOutlineRoundedIcon />} onClick={() => deleteFact(fact)} disabled={working}>删除</Button>
                    </Stack>
                  </Stack>
                </Paper>)}
                {showArchived && archivedFacts.map((fact) => <Paper key={fact.id} variant="outlined" sx={{ p: 2, opacity: 0.72, borderRadius: 1.5 }}>
                  <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={1}><Box><Typography fontWeight={700}>{fact.title}</Typography><Typography variant="body2" color="text.secondary">已归档，不参与生成。</Typography></Box><Tooltip title="恢复事实"><IconButton color="primary" aria-label="恢复事实" onClick={() => restoreFact(fact)} disabled={working}><RestoreRoundedIcon /></IconButton></Tooltip></Stack>
                </Paper>)}
              </Stack>
            </Stack>
          )}

          {tab === 1 && (
            <Stack spacing={2.5}>
              <Paper elevation={0} sx={{ p: 3, borderRadius: 2 }}>
                <Typography variant="h5">导入真实职位</Typography>
                <Typography color="text.secondary" sx={{ mt: 0.5, mb: 2 }}>粘贴公开职位链接，或在受登录、反爬限制时直接粘贴 JD 正文。导入后会保存原文和标准化 JSON。</Typography>
                <Stack spacing={1.5}>
                  <TextField label="职位 URL" type="url" value={jobUrl} onChange={(event) => setJobUrl(event.target.value)} fullWidth />
                  <TextField label="职位描述原文（URL 无法抓取时必填）" value={jobText} onChange={(event) => setJobText(event.target.value)} multiline minRows={8} fullWidth />
                  <Box><Button variant="contained" onClick={importJob} disabled={working || (!jobUrl.trim() && !jobText.trim())}>结构化保存职位</Button></Box>
                </Stack>
              </Paper>
              {jobs.length === 0 && <Alert severity="info">导入职位后，会在这里保存 JD 原文、结构化要求和对岗结果。</Alert>}
              {jobs.map((job) => {
                const requirements = jobRequirements(job);
                const covered = requirements.filter((item) => requirementEvidence(item.text, verifiedFacts).length > 0).length;
                return <Paper key={job.id} elevation={0} sx={{ p: 3, borderRadius: 2 }}>
                  <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={1.5}>
                    <Box><Typography variant="h6">{job.title || '未命名职位'}</Typography><Typography color="text.secondary">{job.company || '公司未提取'}{job.source_url ? ` · ${job.source_url}` : ''}</Typography></Box>
                    <Stack direction="row" spacing={0.5} alignItems="center" useFlexGap flexWrap="wrap"><Button size="small" onClick={() => refreshJob(job.id)} disabled={working || !job.source_url}>重新解析</Button><Tooltip title="编辑职位与要求"><IconButton color="primary" aria-label="编辑职位与要求" onClick={() => setJobEditor(jobToEditor(job))}><EditRoundedIcon /></IconButton></Tooltip><Tooltip title="删除职位和关联版本"><IconButton color="error" aria-label="删除职位" onClick={() => deleteJob(job)} disabled={working}><DeleteOutlineRoundedIcon /></IconButton></Tooltip><Button size="small" startIcon={<RecordVoiceOverRoundedIcon />} onClick={() => navigate('/chat', { state: { interviewJobId: job.id } })}>模拟面试</Button><Button size="small" variant="contained" onClick={() => { setSelectedJobId(String(job.id)); setTab(2); }}>对岗</Button></Stack>
                  </Stack>
                  <Divider sx={{ my: 2 }} />
                  <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
                    <Box sx={{ flex: 1 }}><Typography variant="subtitle2">岗位要求</Typography><Stack direction="row" useFlexGap flexWrap="wrap" gap={0.75} sx={{ mt: 1 }}>{requirements.slice(0, 12).map((item, index) => <Chip key={`${item.group}-${index}`} size="small" label={item.text} color={item.group === '核心要求' ? 'primary' : 'default'} variant={item.group === '核心要求' ? 'filled' : 'outlined'} />)}{requirements.length === 0 && <Typography variant="body2" color="text.secondary">尚未提取到要求，可点击编辑补充。</Typography>}</Stack></Box>
                    <Box sx={{ minWidth: 170 }}><Typography variant="subtitle2">事实库预检</Typography><Typography sx={{ mt: 0.75, fontWeight: 700, color: covered === requirements.length && requirements.length ? 'success.main' : 'text.primary' }}>{covered} / {requirements.length} 项有事实依据</Typography><Typography variant="caption" color="text.secondary">仅作提交前预检，不会编造未覆盖的能力。</Typography></Box>
                  </Stack>
                </Paper>;
              })}
            </Stack>
          )}

          {tab === 2 && (
            <Stack spacing={2.5}>
              <Paper elevation={0} sx={{ p: 3, borderRadius: 2 }}>
                <Typography variant="h5">生成岗位定制简历</Typography>
                <Typography color="text.secondary" sx={{ mt: 0.5, mb: 2 }}>先选择目标职位和可使用的事实，再生成模块化简历。模型只能引用所选已确认事实，并会明确列出缺失项。</Typography>
                <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} alignItems={{ md: 'center' }}>
                  <FormControl fullWidth><InputLabel>目标职位</InputLabel><Select label="目标职位" value={selectedJobId} onChange={(event) => setSelectedJobId(event.target.value)}>{jobs.map((job) => <MenuItem key={job.id} value={String(job.id)}>{job.title} {job.company ? `- ${job.company}` : ''}</MenuItem>)}</Select></FormControl>
                  <Button variant="contained" startIcon={<AutoAwesomeRoundedIcon />} onClick={generateResume} disabled={working || !selectedJobId || selectedFactIds.length === 0 || !currentUser?.full_name?.trim()}>{workingAction === 'generate' ? 'AI 生成中…' : '生成'}</Button>
                </Stack>
                {workingAction === 'generate' && <Alert severity="info" sx={{ mt: 1.5 }}>正在调用 AI 生成定制简历，通常需要 20–60 秒，请不要重复点击。</Alert>}
                {!currentUser?.full_name?.trim() && <Alert severity="warning" sx={{ mt: 1.5 }} action={<Button color="inherit" size="small" onClick={() => navigate('/profile')}>填写姓名</Button>}>投递版简历的姓名只取个人档案中的“真实姓名”，不会使用账号用户名。请先补全后再生成。</Alert>}
                {selectedJob && <Box sx={{ mt: 2.25, p: 2, borderRadius: 1.5, bgcolor: 'action.hover' }}><Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={1}><Box><Typography fontWeight={700}>对岗预检：{matchedPrecheckCount} / {precheck.length} 项已有依据</Typography><Typography variant="body2" color="text.secondary">未覆盖项会作为缺失项保留，不会写成候选人经历。</Typography></Box><Button size="small" onClick={() => setTab(0)}>去补充事实</Button></Stack><Stack spacing={0.75} sx={{ mt: 1.5 }}>{precheck.slice(0, 10).map((item, index) => <Stack key={`${item.text}-${index}`} direction="row" spacing={1} alignItems="center"><Chip size="small" label={item.evidence.length ? '已有依据' : '待补强'} color={item.evidence.length ? 'success' : 'default'} /><Typography variant="body2">{item.text}</Typography>{item.evidence.length > 0 && <Typography variant="caption" color="text.secondary">来自：{item.evidence.map((fact) => fact.title).join('、')}</Typography>}</Stack>)}</Stack></Box>}
                <Typography variant="subtitle2" sx={{ mt: 2.25, mb: 1 }}>本次允许引用的事实（{selectedFactIds.length} / {verifiedFacts.length}）</Typography>
                <Stack direction="row" useFlexGap flexWrap="wrap" gap={0.75}>{verifiedFacts.map((fact) => <Chip key={fact.id} clickable color={selectedFactIds.includes(fact.id) ? 'primary' : 'default'} variant={selectedFactIds.includes(fact.id) ? 'filled' : 'outlined'} onClick={() => setSelectedFactIds((ids) => ids.includes(fact.id) ? ids.filter((id) => id !== fact.id) : [...ids, fact.id])} label={fact.title} />)}{verifiedFacts.length === 0 && <Alert severity="warning">请先在事实库确认至少一条职业事实。</Alert>}</Stack>
              </Paper>
                {resumes.length === 0 ? <Alert severity="info">选择职位并生成后，定制简历版本会保存在这里。</Alert> : resumes.map((resume) => <Paper key={resume.id} elevation={0} sx={{ p: 3, borderRadius: 2 }}><Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={1}><Box><Typography variant="h6">{resumeDisplayTitle(resume)}</Typography><Typography variant="body2" color="text.secondary">版本 {resume.schema_version} · {new Date(resume.created_at).toLocaleString()}</Typography></Box><Stack direction="row" spacing={0.5}><Button size="small" startIcon={<EditRoundedIcon />} onClick={() => navigate(`/resume-optimizer?resumeId=${resume.id}`)}>A4 编辑并保存</Button><Button size="small" startIcon={<VisibilityRoundedIcon />} onClick={() => setPreviewResumeId(String(resume.id))}>预览与导出</Button><Tooltip title="删除定制简历"><IconButton color="error" aria-label="删除定制简历" onClick={() => deleteResume(resume)} disabled={working}><DeleteOutlineRoundedIcon /></IconButton></Tooltip></Stack></Stack><Typography variant="subtitle2" sx={{ mt: 2, mb: 1 }}>匹配分析</Typography><JsonPanel value={resume.match} /></Paper>)}
              {previewResume && <Box sx={{ overflowX: 'auto', pb: 2 }}><Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ md: 'center' }} spacing={1.5} sx={{ mb: 1.5 }}><Box><Typography variant="h6">投递版简历预览</Typography><Typography variant="body2" color="text.secondary">此处直接显示服务端 XeLaTeX 母版生成的 PDF，与下载文件完全一致。</Typography></Box><Stack direction="row" spacing={1}><Button variant="outlined" onClick={() => setPreviewPdfVersion((version) => version + 1)} disabled={previewPdfLoading}>刷新预览</Button><Button variant="outlined" startIcon={<CodeRoundedIcon />} onClick={exportTex} disabled={working}>下载 TeX 源码</Button><Button variant="contained" startIcon={<DownloadRoundedIcon />} onClick={exportPdf} disabled={exportingPdf}>{exportingPdf ? '正在生成 PDF...' : '导出 PDF'}</Button></Stack></Stack><Box sx={{ width: '100%', minWidth: { md: '210mm' }, minHeight: '297mm', bgcolor: '#f3f4f6', boxShadow: '0 8px 28px rgba(0,0,0,0.24)', display: 'grid', placeItems: 'center' }}>{previewPdfLoading && <Stack alignItems="center" spacing={1.5}><CircularProgress /><Typography variant="body2" color="text.secondary">正在按照母版编译预览…</Typography></Stack>}{previewPdfUrl && !previewPdfLoading && <Box component="iframe" title={`${previewResume.title} PDF 预览`} src={previewPdfUrl} sx={{ display: 'block', width: '100%', height: { xs: '78vh', md: 'calc(297mm + 48px)' }, border: 0, bgcolor: '#fff' }} />}</Box></Box>}
            </Stack>
          )}
        </Stack>
      </Container>

      <Dialog open={Boolean(factEditor)} onClose={() => !working && setFactEditor(null)} fullWidth maxWidth="md">
        <DialogTitle>{factEditor?.draftIndex !== undefined ? '编辑待确认事实' : factEditor?.id ? '编辑职业事实' : '新建职业事实'}</DialogTitle>
        <DialogContent dividers>
          <Stack spacing={2} sx={{ pt: 0.5 }}>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
              <FormControl sx={{ minWidth: 155 }}><InputLabel>事实类型</InputLabel><Select label="事实类型" value={factEditor?.fact_type || 'project'} onChange={(event) => setFactEditor((item) => ({ ...item, fact_type: event.target.value }))}>{factTypes.map((type) => <MenuItem key={type} value={type}>{factTypeLabels[type]}</MenuItem>)}</Select></FormControl>
              <TextField fullWidth required label="事实标题" value={factEditor?.title || ''} onChange={(event) => setFactEditor((item) => ({ ...item, title: event.target.value }))} />
            </Stack>
            <TextField fullWidth required multiline minRows={3} label="事实描述" helperText="只写真实、可核查的经历和成果。" value={factEditor?.summary || ''} onChange={(event) => setFactEditor((item) => ({ ...item, summary: event.target.value }))} />
            <TextField fullWidth multiline minRows={3} label="要点（每行一条）" value={factEditor?.highlights || ''} onChange={(event) => setFactEditor((item) => ({ ...item, highlights: event.target.value }))} />
            <TextField fullWidth label="标签（用逗号分隔）" value={factEditor?.tags || ''} onChange={(event) => setFactEditor((item) => ({ ...item, tags: event.target.value }))} />
            <TextField fullWidth multiline minRows={2} label="核查依据" helperText="例如原简历摘录、项目链接或证书名称。" value={factEditor?.evidence || ''} onChange={(event) => setFactEditor((item) => ({ ...item, evidence: event.target.value }))} />
            {factEditor?.draftIndex === undefined && <FormControlLabel control={<Switch checked={Boolean(factEditor?.is_verified)} onChange={(event) => setFactEditor((item) => ({ ...item, is_verified: event.target.checked }))} />} label="已确认，可用于生成简历" />}
          </Stack>
        </DialogContent>
        <DialogActions><Button onClick={() => setFactEditor(null)} disabled={working}>取消</Button><Button variant="contained" startIcon={<SaveRoundedIcon />} onClick={saveFact} disabled={working || !factEditor?.title?.trim() || !(factEditor?.summary?.trim() || factEditor?.highlights?.trim() || factEditor?.evidence?.trim())}>保存事实</Button></DialogActions>
      </Dialog>

      <Dialog open={Boolean(jobEditor)} onClose={() => !working && setJobEditor(null)} fullWidth maxWidth="lg">
        <DialogTitle>编辑职位与结构化要求</DialogTitle>
        <DialogContent dividers>
          <Stack spacing={2} sx={{ pt: 0.5 }}>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}><TextField fullWidth required label="职位名称" value={jobEditor?.title || ''} onChange={(event) => setJobEditor((item) => ({ ...item, title: event.target.value }))} /><TextField fullWidth label="公司" value={jobEditor?.company || ''} onChange={(event) => setJobEditor((item) => ({ ...item, company: event.target.value }))} /></Stack>
            <TextField fullWidth multiline minRows={5} label="JD 摘要" value={jobEditor?.summary || ''} onChange={(event) => setJobEditor((item) => ({ ...item, summary: event.target.value }))} />
            <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5}>
              <TextField fullWidth multiline minRows={5} label="核心要求（每行一项）" value={jobEditor?.required_skills || ''} onChange={(event) => setJobEditor((item) => ({ ...item, required_skills: event.target.value }))} />
              <TextField fullWidth multiline minRows={5} label="工作职责（每行一项）" value={jobEditor?.responsibilities || ''} onChange={(event) => setJobEditor((item) => ({ ...item, responsibilities: event.target.value }))} />
            </Stack>
            <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5}>
              <TextField fullWidth multiline minRows={4} label="加分项（每行一项）" value={jobEditor?.preferred_skills || ''} onChange={(event) => setJobEditor((item) => ({ ...item, preferred_skills: event.target.value }))} />
              <TextField fullWidth multiline minRows={4} label="关键词（每行一项）" value={jobEditor?.keywords || ''} onChange={(event) => setJobEditor((item) => ({ ...item, keywords: event.target.value }))} />
            </Stack>
            <TextField fullWidth multiline minRows={5} label="JD 原文" helperText="保存后可重新解析；此处修改不会自动改写你的事实库。" value={jobEditor?.raw_content || ''} onChange={(event) => setJobEditor((item) => ({ ...item, raw_content: event.target.value }))} />
          </Stack>
        </DialogContent>
        <DialogActions><Button onClick={() => setJobEditor(null)} disabled={working}>取消</Button><Button variant="contained" startIcon={<SaveRoundedIcon />} onClick={saveJob} disabled={working || !jobEditor?.title?.trim() || !jobEditor?.raw_content?.trim()}>保存职位要求</Button></DialogActions>
      </Dialog>
    </Box>
  );
};

export default CareerStudio;
