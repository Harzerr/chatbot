import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  AppBar,
  Avatar,
  Box,
  Button,
  Chip,
  CircularProgress,
  Container,
  Divider,
  Paper,
  Stack,
  TextField,
  Toolbar,
  Typography,
} from '@mui/material';
import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded';
import DescriptionRoundedIcon from '@mui/icons-material/DescriptionRounded';
import UploadFileRoundedIcon from '@mui/icons-material/UploadFileRounded';
import SaveRoundedIcon from '@mui/icons-material/SaveRounded';
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded';
import AddRoundedIcon from '@mui/icons-material/AddRounded';
import LogoutIcon from '@mui/icons-material/Logout';
import WorkOutlineRoundedIcon from '@mui/icons-material/WorkOutlineRounded';
import { useAuth } from '../contexts/AuthContext';
import chatService from '../services/chatService';
import ProfileGrowthReport from '../components/ProfileGrowthReport';

const HISTORY_PAGE_SIZE = 100;
const HISTORY_MAX_PAGES = 20;

const Profile = () => {
  const navigate = useNavigate();
  const {
    currentUser,
    loading,
    error,
    refreshCurrentUser,
    updateProfile,
    uploadResume,
    uploadAvatar,
    deleteAvatar,
    logout,
  } = useAuth();

  const [form, setForm] = useState({
    username: '',
    full_name: '',
    email: '',
    phone: '',
    target_role: '',
    years_of_experience: 0,
    bio: '',
  });
  const [saveLoading, setSaveLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [avatarUploading, setAvatarUploading] = useState(false);
  const [education, setEducation] = useState([]);
  const [message, setMessage] = useState('');
  const [growthLoading, setGrowthLoading] = useState(false);
  const [growthError, setGrowthError] = useState('');
  const [interviewMessages, setInterviewMessages] = useState([]);

  const loadGrowthReport = useCallback(async () => {
    setGrowthLoading(true);
    setGrowthError('');
    try {
      const allMessages = [];

      for (let page = 0; page < HISTORY_MAX_PAGES; page += 1) {
        const offset = page * HISTORY_PAGE_SIZE;
        const response = await chatService.getUserChats(HISTORY_PAGE_SIZE, offset);
        const batch = Array.isArray(response?.messages) ? response.messages : [];

        allMessages.push(...batch);

        if (batch.length < HISTORY_PAGE_SIZE) {
          break;
        }
      }

      setInterviewMessages(allMessages);
    } catch (err) {
      console.error('Failed to load growth report data:', err);
      setGrowthError('加载成长分析数据失败，请稍后重试。');
    } finally {
      setGrowthLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshCurrentUser().catch((err) => {
      console.error('Failed to refresh profile:', err);
    });
  }, [refreshCurrentUser]);

  useEffect(() => {
    loadGrowthReport().catch((err) => {
      console.error('Failed to initialize growth report:', err);
    });
  }, [loadGrowthReport]);

  useEffect(() => {
    if (!currentUser) return;
    setForm({
      username: currentUser.username || '',
      full_name: currentUser.full_name || '',
      email: currentUser.email || '',
      phone: currentUser.phone || '',
      target_role: currentUser.target_role || '',
      years_of_experience: currentUser.years_of_experience ?? 0,
      bio: currentUser.bio || '',
    });
    setEducation(Array.isArray(currentUser.education) ? currentUser.education : []);
  }, [currentUser]);

  const handleChange = (field) => (event) => {
    const value = field === 'years_of_experience' ? Number(event.target.value) : event.target.value;
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  const handleSave = async (event) => {
    event.preventDefault();
    setMessage('');
    setSaveLoading(true);
    try {
      await updateProfile({ ...form, education });
      setMessage('个人档案已更新。');
    } catch (err) {
      console.error('Profile save failed:', err);
    } finally {
      setSaveLoading(false);
    }
  };

  const addEducation = () => {
    setEducation((items) => [...items, { school: '', degree: '', major: '', start_date: '', end_date: '', rank: '', gpa: '', english_level: '', details: '' }]);
  };

  const updateEducation = (index, field) => (event) => {
    setEducation((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, [field]: event.target.value } : item));
  };

  const removeEducation = (index) => {
    setEducation((items) => items.filter((_, itemIndex) => itemIndex !== index));
  };

  const handleResumeUpload = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setMessage('');
    setUploading(true);
    try {
      const response = await uploadResume(file);
      setMessage(`简历上传成功，系统已完成解析。文件：${response.file_name}`);
      await loadGrowthReport();
    } catch (err) {
      console.error('Resume upload failed:', err);
    } finally {
      setUploading(false);
      event.target.value = '';
    }
  };

  const handleAvatarUpload = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 5 * 1024 * 1024) {
      setMessage('头像请选择小于 5 MB 的 PNG、JPG 或 WEBP 图片。');
      event.target.value = '';
      return;
    }
    setMessage('');
    setAvatarUploading(true);
    try {
      await uploadAvatar(file);
      setMessage('头像已更新，将用于后续简历预览和 PDF 导出。');
    } catch (err) {
      console.error('Avatar upload failed:', err);
    } finally {
      setAvatarUploading(false);
      event.target.value = '';
    }
  };

  const handleAvatarDelete = async () => {
    if (!window.confirm('移除个人头像？后续生成和导出的简历将不显示头像。')) return;
    setMessage('');
    try {
      await deleteAvatar();
      setMessage('头像已移除。');
    } catch (err) {
      console.error('Avatar deletion failed:', err);
    }
  };

  if (loading && !currentUser) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh' }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box sx={{ minHeight: '100vh' }}>
      <AppBar position="sticky">
        <Toolbar sx={{ gap: 1.5 }}>
          <Button color="inherit" startIcon={<ArrowBackRoundedIcon />} onClick={() => navigate('/chat')}>
            返回面试
          </Button>
          <Box sx={{ flexGrow: 1 }}>
            <Typography variant="h6">个人档案</Typography>
          </Box>
          <Button color="inherit" startIcon={<WorkOutlineRoundedIcon />} onClick={() => navigate('/career')}>
            求职工作台
          </Button>
          <Button
            color="inherit"
            onClick={() => {
              logout();
              navigate('/login');
            }}
            startIcon={<LogoutIcon />}
          >
            退出登录
          </Button>
        </Toolbar>
      </AppBar>

      <Container maxWidth="lg" sx={{ py: 4 }}>
        <Stack spacing={3}>
          {(error || message) && (
            <Alert severity={error ? 'error' : 'success'}>
              {error || message}
            </Alert>
          )}

          <Paper elevation={0} sx={{ p: 3, borderRadius: 3 }}>
            <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} justifyContent="space-between">
              <Box>
                <Typography variant="h5" sx={{ fontWeight: 700 }}>
                  候选人资料
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1, maxWidth: 720, lineHeight: 1.7 }}>
                  这里的真实姓名、邮箱和手机号是投递版简历的唯一抬头来源。上传简历只保存原文供提取事实，不会自动覆盖这些字段。
                </Typography>
              </Box>
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} alignItems={{ sm: 'center' }}>
                <Chip
                  icon={<DescriptionRoundedIcon />}
                  label={currentUser?.has_resume ? `已上传简历：${currentUser.resume_file_name}` : '尚未上传简历'}
                  sx={{
                    bgcolor: currentUser?.has_resume ? 'rgba(52,211,153,0.14)' : 'rgba(245,158,11,0.12)',
                    color: currentUser?.has_resume ? '#047857' : '#a16207',
                  }}
                />
                <Stack direction="row" spacing={1.25} alignItems="center">
                  <Avatar src={currentUser?.avatar_url || undefined} alt={currentUser?.full_name || '个人头像'} sx={{ width: 72, height: 72, border: '2px solid', borderColor: 'primary.main' }}>{currentUser?.full_name?.trim()?.slice(0, 1) || '我'}</Avatar>
                  <Stack spacing={0.5} alignItems="flex-start">
                    <Button component="label" size="small" variant="outlined" startIcon={<UploadFileRoundedIcon />} disabled={avatarUploading}>
                      {avatarUploading ? '上传中...' : currentUser?.avatar_url ? '更换头像' : '上传头像'}
                      <input hidden type="file" accept="image/png,image/jpeg,image/webp" onChange={handleAvatarUpload} />
                    </Button>
                    {currentUser?.avatar_url && <Button size="small" color="error" startIcon={<DeleteOutlineRoundedIcon />} onClick={handleAvatarDelete}>移除头像</Button>}
                    <Typography variant="caption" color="text.secondary">PNG、JPG、WEBP，最大 5 MB</Typography>
                  </Stack>
                </Stack>
              </Stack>
            </Stack>
          </Paper>

          <Stack direction={{ xs: 'column', lg: 'row' }} spacing={3} alignItems="stretch">
            <Paper elevation={0} sx={{ p: 3, borderRadius: 3, flex: 1.2 }}>
              <Typography variant="h6" sx={{ mb: 2 }}>
                用于简历的个人信息
              </Typography>
              <Box component="form" onSubmit={handleSave}>
                <Stack spacing={2}>
                  <TextField label="账号用户名" value={form.username} fullWidth disabled helperText="仅用于登录，不会出现在投递版简历中。" />
                  <TextField required label="真实姓名（简历抬头）" value={form.full_name} onChange={handleChange('full_name')} fullWidth helperText="生成和导出简历时使用此姓名。" />
                  <TextField label="邮箱（简历联系方式）" type="email" value={form.email} onChange={handleChange('email')} fullWidth />
                  <TextField label="手机号（简历联系方式）" value={form.phone} onChange={handleChange('phone')} fullWidth />
                  <TextField label="目标岗位" value={form.target_role} onChange={handleChange('target_role')} fullWidth />
                  <TextField
                    label="工作年限"
                    type="number"
                    inputProps={{ min: 0, max: 50 }}
                    value={form.years_of_experience}
                    onChange={handleChange('years_of_experience')}
                    fullWidth
                  />
                  <TextField
                    label="个人简介"
                    value={form.bio}
                    onChange={handleChange('bio')}
                    fullWidth
                    multiline
                    minRows={5}
                  />
                  <Divider />
                  <Stack spacing={1.5}>
                    <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ sm: 'center' }} spacing={1}>
                      <Box><Typography variant="h6">教育背景</Typography><Typography variant="body2" color="text.secondary">固定展示在每份简历的教育背景栏目，不由 JD 改写。</Typography></Box>
                      <Button size="small" variant="outlined" startIcon={<AddRoundedIcon />} onClick={addEducation}>添加教育经历</Button>
                    </Stack>
                    {education.map((entry, index) => <Box key={index} sx={{ p: 1.5, border: '1px solid', borderColor: 'divider', borderRadius: 1.5 }}>
                      <Stack spacing={1.25}>
                        <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.25}><TextField required fullWidth label="学校" value={entry.school} onChange={updateEducation(index, 'school')} /><TextField fullWidth label="专业" value={entry.major} onChange={updateEducation(index, 'major')} /><TextField fullWidth label="学历" value={entry.degree} onChange={updateEducation(index, 'degree')} /></Stack>
                        <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.25}><TextField fullWidth label="开始时间" placeholder="2024.09" value={entry.start_date} onChange={updateEducation(index, 'start_date')} /><TextField fullWidth label="结束时间" placeholder="2027.06" value={entry.end_date} onChange={updateEducation(index, 'end_date')} /><TextField fullWidth label="排名" value={entry.rank} onChange={updateEducation(index, 'rank')} /><TextField fullWidth label="GPA" value={entry.gpa} onChange={updateEducation(index, 'gpa')} /><TextField fullWidth label="英语水平" placeholder="CET-6" value={entry.english_level || ''} onChange={updateEducation(index, 'english_level')} /></Stack>
                        <Stack direction="row" spacing={1} alignItems="flex-start"><TextField fullWidth multiline minRows={2} label="科研、课程或其他固定说明" value={entry.details} onChange={updateEducation(index, 'details')} /><Button color="error" startIcon={<DeleteOutlineRoundedIcon />} onClick={() => removeEducation(index)}>删除</Button></Stack>
                      </Stack>
                    </Box>)}
                    {education.length === 0 && <Alert severity="info">添加后，教育经历会固定在投递版简历中；项目和实习经历仍由 JD 定制。</Alert>}
                  </Stack>
                  <Button type="submit" variant="contained" startIcon={<SaveRoundedIcon />} disabled={saveLoading}>
                    {saveLoading ? '保存中...' : '保存个人信息'}
                  </Button>
                </Stack>
              </Box>
            </Paper>

            <Paper elevation={0} sx={{ p: 3, borderRadius: 3, flex: 1 }}>
              <Typography variant="h6" sx={{ mb: 2 }}>
                简历上传
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.75 }}>
                支持上传 PDF、PNG、JPG、JPEG、WEBP。上传后系统会自动提取简历文本，用于事实提取和模拟面试；不会覆盖左侧已填写的姓名或联系方式。
              </Typography>

              <Button
                component="label"
                variant="outlined"
                startIcon={<UploadFileRoundedIcon />}
                disabled={uploading}
                sx={{ mt: 2, borderRadius: 2 }}
              >
                {uploading ? '上传并解析中...' : '上传简历'}
                <input
                  hidden
                  type="file"
                  accept=".pdf,image/png,image/jpeg,image/jpg,image/webp"
                  onChange={handleResumeUpload}
                />
              </Button>

              <Paper
                elevation={0}
                sx={{
                  mt: 2.5,
                  p: 2,
                  borderRadius: 2,
                  bgcolor: '#f8fafc',
                  border: '1px solid rgba(71,85,105,0.18)',
                }}
              >
                <Typography variant="subtitle2" sx={{ color: '#0f172a', mb: 1 }}>
                  当前简历状态
                </Typography>
                {currentUser?.has_resume ? (
                  <>
                    <Typography variant="body2" sx={{ color: '#1e293b', lineHeight: 1.8 }}>
                      文件名：{currentUser.resume_file_name}
                    </Typography>
                    <Typography variant="body2" sx={{ color: '#475569', lineHeight: 1.8 }}>
                      上传时间：{currentUser.resume_uploaded_at}
                    </Typography>
                    <Typography variant="body2" sx={{ color: '#334155', mt: 1.2, lineHeight: 1.8, whiteSpace: 'pre-wrap' }}>
                      {currentUser.resume_excerpt}
                    </Typography>
                  </>
                ) : (
                  <Typography variant="body2" sx={{ color: '#a16207', lineHeight: 1.8 }}>
                    还没有上传简历。开始新面试前建议先上传简历。
                  </Typography>
                )}
              </Paper>
            </Paper>
          </Stack>

          <ProfileGrowthReport
            messages={interviewMessages}
            loading={growthLoading}
            error={growthError}
            onRetry={loadGrowthReport}
          />
        </Stack>
      </Container>
    </Box>
  );
};

export default Profile;
